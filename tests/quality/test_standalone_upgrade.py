"""Original-pin rejection and real owned directory-replacement controller controls."""

import base64
import hashlib
import io
import json
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

from scripts import verify_standalone as verifier
from scripts.standalone import TARGETS
from scripts.supply_chain import digest
from tests.support import published_standalone as published
from tests.support import source_candidate
from tests.support.native_release import candidates

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(params=TARGETS)
def public_originals(request, tmp_path, monkeypatch):
    target = request.param
    candidates(ROOT, published.SOURCE, published.VERSION, tmp_path / "originals")
    directory = tmp_path / "originals/standalone" / target / "candidate"
    manifest = json.loads((directory / "build-manifest.json").read_bytes())
    archive = directory / manifest["archive"]["name"]
    provenance = archive.name.removesuffix(".tar.gz") + ".provenance.json"
    files = {
        archive.name: archive.read_bytes(),
        provenance: json.dumps(
            {
                "schema_version": 1,
                "target": target,
                "records": {
                    "candidate/build-manifest.json": base64.b64encode(
                        (directory / "build-manifest.json").read_bytes()
                    ).decode()
                },
            }
        ).encode(),
    }
    pin = {
        "archive": hashlib.sha256(files[archive.name]).hexdigest(),
        "provenance": hashlib.sha256(files[provenance]).hexdigest(),
    }
    files[published.CHECKSUM_NAME] = (
        pin["archive"] + "  " + archive.name + "\n" + pin["provenance"] + "  " + provenance + "\n"
    ).encode()
    monkeypatch.setattr(published, "PINS", {target: pin})
    monkeypatch.setattr(
        published, "CHECKSUM_SHA256", hashlib.sha256(files[published.CHECKSUM_NAME]).hexdigest()
    )
    monkeypatch.setattr(
        published,
        "urlopen",
        lambda url, timeout: io.BytesIO(files[url.removeprefix(published.BASE_URL)]),
    )
    return target, files, manifest


def test_four_target_predecessors_retain_original_bytes_and_refuse_overwrite(
    public_originals, tmp_path
):
    target, files, manifest = public_originals
    archive, actual = published.predecessor(tmp_path / "download", "0.5.0", target)
    assert actual == manifest
    assert archive.read_bytes() == files[archive.name]
    assert {p.name: p.read_bytes() for p in archive.parent.iterdir()} == files
    with pytest.raises(FileExistsError):
        published.predecessor(tmp_path / "download", "0.5.0", target)


@pytest.mark.parametrize(
    "fault",
    [
        "checksum",
        "provenance",
        "archive",
        "inventory",
        "candidate-source",
        "candidate-version",
        "target",
    ],
)
def test_wrong_or_corrupt_published_native_identity_fails_before_execution(
    public_originals, tmp_path, monkeypatch, fault
):
    target, files, manifest = public_originals
    name = manifest["archive"]["name"]
    sidecar = name.removesuffix(".tar.gz") + ".provenance.json"
    if fault in {"checksum", "provenance", "archive"}:
        filename = {"checksum": published.CHECKSUM_NAME, "provenance": sidecar, "archive": name}[
            fault
        ]
        files[filename] += b"corrupt"
    else:
        if fault == "inventory":
            manifest["archive"]["members"] = {}
        elif fault == "candidate-source":
            manifest["source_commit"] = "a" * 40
        elif fault == "candidate-version":
            manifest["version"] = "0.5.0"
        else:
            manifest["target"] = "other"
        data = json.loads(files[sidecar])
        data["records"]["candidate/build-manifest.json"] = base64.b64encode(
            json.dumps(manifest).encode()
        ).decode()
        files[sidecar] = json.dumps(data).encode()
        published.PINS[target]["provenance"] = hashlib.sha256(files[sidecar]).hexdigest()
        files[published.CHECKSUM_NAME] = (
            published.PINS[target]["archive"]
            + "  "
            + name
            + "\n"
            + published.PINS[target]["provenance"]
            + "  "
            + sidecar
            + "\n"
        ).encode()
        monkeypatch.setattr(
            published, "CHECKSUM_SHA256", hashlib.sha256(files[published.CHECKSUM_NAME]).hexdigest()
        )
    with pytest.raises(ValueError):
        published.predecessor(tmp_path / "download", "0.5.0", target)


def test_unreviewed_next_publication_is_refused_without_network(tmp_path, monkeypatch):
    monkeypatch.setattr(
        source_candidate,
        "published_baseline",
        lambda _: {"version": "0.5.0", "source_commit": "a" * 40},
    )

    def unexpected(*args, **kwargs):
        pytest.fail("An unreviewed native predecessor must not be downloaded")

    monkeypatch.setattr(published, "urlopen", unexpected)
    with pytest.raises(ValueError, match="reviewed immutable"):
        published.predecessor(tmp_path / "download", "0.6.0", "linux-x86_64")


@pytest.fixture
def replaceable(tmp_path, monkeypatch):
    """Shell processes test replacement/cleanup only; they are not native proof."""

    def artifact(version):
        directory = tmp_path / version
        bundle = directory / "kuberich"
        bundle.mkdir(parents=True)
        executable = bundle / "kuberich"
        executable.write_text(
            '#!/bin/sh\ncase "$1" in\n--version) printf \'kuberich ' + version + "\\n';;\n"
            "--help) printf 'usage: kuberich\\n';;\ninfo) printf '%s\\n' '"
            + json.dumps(
                {
                    "version": version,
                    "cluster_connected": False,
                    "preferences": {"read_only": True, "refresh_seconds": 1.5},
                }
            )
            + "';;\nesac\n"
        )
        executable.chmod(0o755)
        (bundle / ("payload-" + version)).write_text(version)
        archive = directory / ("kuberich-" + version + "-linux-x86_64.tar.gz")
        with tarfile.open(archive, "w:gz") as output:
            output.add(bundle, arcname="kuberich")
        return archive, {
            "source_commit": published.SOURCE if version == "0.4.0" else "a" * 40,
            "version": version,
            "target": "linux-x86_64",
            "archive": {"name": archive.name, "sha256": digest(archive)},
        }

    old, old_manifest = artifact("0.4.0")
    new, manifest = artifact("0.5.0")
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    original_configurations = []

    def predecessor(directory, version, target):
        directory.mkdir()
        shutil.copyfile(old, directory / old.name)
        (directory / old.name.replace(".tar.gz", ".provenance.json")).write_bytes(
            b"original provenance"
        )
        (directory / published.CHECKSUM_NAME).write_bytes(b"original checksums")
        return directory / old.name, old_manifest

    monkeypatch.setattr(verifier, "predecessor", predecessor)
    monkeypatch.setattr(
        verifier,
        "PINS",
        {
            "linux-x86_64": {
                "archive": digest(old),
                "provenance": hashlib.sha256(b"original provenance").hexdigest(),
            }
        },
    )
    monkeypatch.setattr(
        verifier, "CHECKSUM_SHA256", hashlib.sha256(b"original checksums").hexdigest()
    )
    monkeypatch.setattr(verifier, "inspect_bundle", lambda *_: None)

    class OwnedHost:
        linux = False

        def __init__(self, bundle, directory, evidence):
            self.bundle, self.directory, self.evidence = bundle, directory, evidence
            self.executable = str(bundle / "kuberich")

        def observe(self, name, argv, environment):
            result = subprocess.run(
                argv,
                cwd=self.directory,
                env=environment,
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
            verifier.write_original(
                self.evidence / (name + ".json"),
                {
                    "argv": argv,
                    "cwd": str(self.directory),
                    "exit": result.returncode,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                },
            )
            original_configurations.append(
                verifier.retained_configuration(
                    (Path(environment["KUBERICH_CONFIG"]), Path(environment["KUBECONFIG"]))
                )
            )
            return result.stdout

        def close(self):
            pass

    monkeypatch.setattr(verifier, "Host", OwnedHost)

    def browser(host, directory, evidence, **kwargs):
        assert not (host.bundle / "payload-0.4.0").exists()
        assert not (host.bundle / ".owned-predecessor-only").exists()
        assert (host.bundle / "payload-0.5.0").read_text() == "0.5.0"
        assert (
            subprocess.check_output([host.executable, "--version"], text=True) == "kuberich 0.5.0\n"
        )
        return {"controlled_fixture_only": True}

    monkeypatch.setattr(verifier, "browser", browser)
    return new.parent, manifest, tmp_path / "trial", evidence, original_configurations


def test_complete_directory_replacement_runs_both_real_processes_and_removes_only_install(
    replaceable,
):
    candidate, manifest, directory, evidence, configurations = replaceable
    result = verifier.replacement(candidate, manifest, directory, evidence)
    receipt = json.loads((evidence / result["receipt"]).read_bytes())
    assert receipt["result"] == "passed"
    assert receipt["complete_directory_replaced"] and receipt["original_archive_hashes_unchanged"]
    assert receipt["owned_installation_removed"] and not (directory / "install/kuberich").exists()
    assert len(configurations) == 6 and all(c == configurations[0] for c in configurations)
    assert configurations[0] == receipt["configuration_after_cleanup"]
    assert [(c["phase"], c["operation"]) for c in receipt["commands"]] == [
        (p, o) for p in ("old", "new") for o in ("version", "help", "info")
    ]
    assert (evidence / "upgrade" / receipt["old_archive"]).is_file()


def test_failed_post_replacement_observation_preserves_original_failure_and_owned_cleanup(
    replaceable, monkeypatch
):
    candidate, manifest, directory, evidence, _ = replaceable

    def failed(*args, **kwargs):
        raise RuntimeError("owned observer failure")

    monkeypatch.setattr(verifier, "browser", failed)
    with pytest.raises(RuntimeError, match="owned observer failure"):
        verifier.replacement(candidate, manifest, directory, evidence)
    receipt = json.loads((evidence / "upgrade-replacement.json").read_bytes())
    assert receipt["result"] == "failed" and receipt["error"] == "RuntimeError"
    assert receipt["owned_installation_removed"]
    assert receipt["configuration_before"] == receipt["configuration_after_cleanup"]
    assert (evidence / "upgrade/old-version.json").is_file()
    assert (evidence / "upgrade/new-version.json").is_file()


@pytest.mark.parametrize("operation_failure", [False, True])
def test_host_close_refusal_still_removes_install_checks_configuration_and_retains_failures(
    replaceable, monkeypatch, operation_failure
):
    candidate, manifest, directory, evidence, _ = replaceable
    cleanup_error = RuntimeError("owned host-close refusal")
    primary_error = ValueError("owned primary observer failure")

    def close(host):
        raise cleanup_error

    def failed(*args, **kwargs):
        raise primary_error

    monkeypatch.setattr(verifier.Host, "close", close)
    if operation_failure:
        monkeypatch.setattr(verifier, "browser", failed)
    with pytest.raises(ExceptionGroup) as raised:
        verifier.replacement(candidate, manifest, directory, evidence)
    assert raised.value.exceptions == (
        (primary_error, cleanup_error) if operation_failure else (cleanup_error,)
    )
    receipt = json.loads((evidence / "upgrade-replacement.json").read_bytes())
    assert receipt["result"] == "failed"
    assert receipt["cleanup_errors"] == [{"stage": "host_close", "error": "RuntimeError"}]
    assert receipt["owned_installation_removed"] and not (directory / "install/kuberich").exists()
    assert receipt["configuration_before"] == receipt["configuration_after_cleanup"]
    if operation_failure:
        assert receipt["error"] == "ValueError"
