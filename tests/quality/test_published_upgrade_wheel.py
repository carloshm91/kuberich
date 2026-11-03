"""Offline rejection controls for public wheel pins and locked dependency availability."""

import hashlib
import io
import zipfile

import pytest

from tests.support import published_wheel as published


def wheel(tmp_path, *, version="0.2.0", name="kuberich", requires=()):
    path = tmp_path / "kuberich-0.2.0-py3-none-any.whl"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "kuberich-0.2.0.dist-info/METADATA",
            f"Metadata-Version: 2.3\nName: {name}\nVersion: {version}\n"
            + "".join(f"Requires-Dist: {requirement}\n" for requirement in requires),
        )
    return path, {
        "url": "https://files.pythonhosted.org/packages/owned/" + path.name,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def test_immutable_wheel_is_checked_before_use_and_download_is_exclusive(tmp_path, monkeypatch):
    path, pin = wheel(tmp_path)
    original = path.read_bytes()
    monkeypatch.setattr(published, "PUBLISHED_WHEELS", {"0.2.0": pin})
    monkeypatch.setattr(published, "urlopen", lambda url, timeout: io.BytesIO(original))
    downloaded, receipt = published.published_upgrade_wheel(tmp_path / "download", "0.3.0")
    assert downloaded.read_bytes() == original
    assert receipt["version"] == "0.2.0" and receipt["sha256"] == pin["sha256"]
    assert receipt["source_commit"] and receipt["github"].endswith("/v0.2.0")
    with pytest.raises(FileExistsError):
        published.published_upgrade_wheel(tmp_path / "download", "0.3.0")


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
    monkeypatch.setattr(published, "published_baseline", lambda _: {"version": "0.3.0"})
    with pytest.raises(ValueError, match="reviewed immutable"):
        published.published_upgrade_wheel(tmp_path / "download", "0.4.0")


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
