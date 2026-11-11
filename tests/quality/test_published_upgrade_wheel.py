"""Offline rejection controls for public wheel pins and locked dependency availability."""

import hashlib
import io
import zipfile

import pytest

from tests.support import published_wheel as published


def test_04_candidate_has_a_reviewed_real_03_predecessor_pin():
    baseline = published.published_baseline("0.4.0")
    assert baseline["version"] == "0.3.0"
    assert baseline["version"] in published.PUBLISHED_WHEELS


def test_05_candidate_has_the_reviewed_real_04_predecessor_pin():
    baseline = published.published_baseline("0.5.0")
    assert baseline["version"] == "0.4.0"
    assert baseline["source_commit"] == "78ff8f720d4ffde34ea91193593823685433515f"
    assert published.PUBLISHED_WHEELS["0.4.0"]["sha256"] == (
        "a3168424374dceb2b804900ff4b6a25bbead14ffa5c6d132b5b872f0b73676fd"
    )


def wheel(tmp_path, *, version="0.2.0", filename_version="0.2.0", name="kuberich", requires=()):
    path = tmp_path / f"kuberich-{filename_version}-py3-none-any.whl"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            f"kuberich-{filename_version}.dist-info/METADATA",
            f"Metadata-Version: 2.3\nName: {name}\nVersion: {version}\n"
            + "".join(f"Requires-Dist: {requirement}\n" for requirement in requires),
        )
    return path, {
        "url": "https://files.pythonhosted.org/packages/owned/" + path.name,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


@pytest.mark.parametrize(
    "baseline,candidate", [("0.2.0", "0.3.0"), ("0.3.0", "0.4.0"), ("0.4.0", "0.5.0")]
)
def test_immutable_wheel_is_checked_before_use_and_download_is_exclusive(
    tmp_path, monkeypatch, baseline, candidate
):
    path, pin = wheel(tmp_path, version=baseline, filename_version=baseline)
    original = path.read_bytes()
    monkeypatch.setattr(published, "PUBLISHED_WHEELS", {baseline: pin})
    monkeypatch.setattr(published, "urlopen", lambda url, timeout: io.BytesIO(original))
    downloaded, receipt = published.published_upgrade_wheel(tmp_path / "download", candidate)
    assert downloaded.read_bytes() == original
    assert receipt["version"] == baseline and receipt["sha256"] == pin["sha256"]
    assert receipt["source_commit"] and receipt["github"].endswith("/v" + baseline)
    with pytest.raises(FileExistsError):
        published.published_upgrade_wheel(tmp_path / "download", candidate)


@pytest.mark.parametrize("fault", ["bytes", "version", "name", "zip", "size"])
def test_current_candidate_or_corrupt_bytes_cannot_be_called_the_public_baseline(
    tmp_path, monkeypatch, fault
):
    path, pin = wheel(
        tmp_path,
        version="0.3.0" if fault == "version" else "0.2.0",
        name="other" if fault == "name" else "kuberich",
    )
    if fault == "bytes":
        path.write_bytes(path.read_bytes() + b"modified")
    elif fault == "zip":
        path.write_bytes(b"not a wheel")
        pin["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    elif fault == "size":
        monkeypatch.setattr(published, "MAX_WHEEL_BYTES", 8)
    with pytest.raises(ValueError):
        published.verify_published_wheel(path, "0.2.0", pin)


@pytest.mark.parametrize(
    "url",
    [
        "https://other.invalid/kuberich-0.2.0-py3-none-any.whl",
        "https://files.pythonhosted.org/other.whl",
        "https://files.pythonhosted.org/kuberich-0.2.0-py3-none-any.whl?token=owned",
    ],
)
def test_unreviewed_url_is_refused_before_a_network_request(tmp_path, monkeypatch, url):
    _, pin = wheel(tmp_path)
    monkeypatch.setattr(published, "PUBLISHED_WHEELS", {"0.2.0": {**pin, "url": url}})

    def unexpected(*args, **kwargs):
        pytest.fail("Unreviewed public wheel URL must never be requested")

    monkeypatch.setattr(published, "urlopen", unexpected)
    with pytest.raises(ValueError, match="reviewed canonical"):
        published.published_upgrade_wheel(tmp_path / "download", "0.3.0")


def test_a_later_predecessor_requires_its_own_reviewed_wheel_pin(tmp_path, monkeypatch):
    monkeypatch.setattr(published, "PUBLISHED_WHEELS", {})
    with pytest.raises(ValueError, match="reviewed immutable"):
        published.published_upgrade_wheel(tmp_path / "download", "0.5.0")


@pytest.mark.parametrize("fault", ["bytes", "candidate-version", "wrong-name"])
def test_reviewed_04_predecessor_refuses_corruption_or_candidate_identity(tmp_path, fault):
    path, pin = wheel(
        tmp_path,
        version="0.5.0" if fault == "candidate-version" else "0.4.0",
        filename_version="0.4.0",
        name="other" if fault == "wrong-name" else "kuberich",
    )
    if fault == "bytes":
        path.write_bytes(path.read_bytes() + b"changed original")
    with pytest.raises(ValueError):
        published.verify_published_wheel(path, "0.4.0", pin)


def test_existing_locked_wheels_must_satisfy_actual_old_and_new_metadata(tmp_path):
    path, _ = wheel(tmp_path, requires=("textual==8.2.8", 'unused; python_version < "1"'))
    dependencies = tmp_path / "locked"
    dependencies.mkdir()
    wrong = dependencies / "textual-8.2.7-py3-none-any.whl"
    wrong.write_bytes(b"owned test wheel name")
    with pytest.raises(AssertionError, match=r"textual==8\.2\.8"):
        published.require_wheelhouse(path, dependencies)
    wrong.rename(dependencies / "textual-8.2.8-py3-none-any.whl")
    published.require_wheelhouse(path, dependencies)
