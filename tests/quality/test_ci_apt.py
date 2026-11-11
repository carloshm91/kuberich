"""APT bootstrap contracts use only an owned mirror file and fake command handles."""

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import ci_apt


@pytest.fixture(autouse=True)
def refuse_real_commands(monkeypatch, tmp_path):
    def refuse(*args, **kwargs):
        raise AssertionError("This test must never execute dpkg, sudo, APT or any real command.")

    monkeypatch.setattr(ci_apt.subprocess, "run", refuse)
    monkeypatch.setattr(ci_apt, "MIRROR_FILE", tmp_path / "owned-apt-mirrors.txt")
    monkeypatch.setattr(ci_apt, "SOURCE_LIST", tmp_path / "sources.list")
    monkeypatch.setattr(ci_apt, "SOURCE_DIRECTORY", tmp_path / "sources.list.d")
    ci_apt.SOURCE_LIST.write_text("deb mirror+file:/etc/apt/apt-mirrors.txt noble main universe\n")
    ci_apt.SOURCE_DIRECTORY.mkdir()
    monkeypatch.setattr(ci_apt.platform, "system", lambda: "Linux")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("RUNNER_OS", "Linux")


@pytest.fixture
def owned_commands(monkeypatch):
    ci_apt.MIRROR_FILE.write_text("http://azure.archive.ubuntu.com/ubuntu\n")
    fixture = SimpleNamespace(calls=[], architecture=b"amd64\n", fail_phase=None, failure=None)

    def command(argv, **kwargs):
        assert isinstance(argv, tuple) and all(isinstance(part, str) for part in argv)
        assert kwargs["check"] is True and not kwargs.get("shell", False)
        if argv == ("/usr/bin/dpkg", "--print-architecture"):
            phase = "architecture"
        elif "/usr/bin/tee" in argv:
            phase = "mirror"
        elif "update" in argv:
            phase = "update"
        else:
            assert "install" in argv
            phase = "install"
        fixture.calls.append((phase, argv, kwargs))
        if phase == fixture.fail_phase:
            raise fixture.failure
        if phase == "mirror":
            path = Path(argv[-1])
            assert path in {ci_apt.MIRROR_FILE, ci_apt.SOURCE_LIST}
            assert len(kwargs["input"]) <= 65536
            path.write_bytes(kwargs["input"])
        return subprocess.CompletedProcess(argv, 0, stdout=fixture.architecture)

    monkeypatch.setattr(ci_apt.subprocess, "run", command)
    return fixture


@pytest.mark.parametrize(
    "architecture,mirror",
    [
        ("amd64", "https://mirrors.mit.edu/ubuntu"),
        ("arm64", "https://mirrors.mit.edu/ubuntu-ports"),
    ],
)
def test_architecture_selects_only_the_official_matching_https_archive(architecture, mirror):
    assert ci_apt.mirror_for_architecture(architecture) == mirror


@pytest.mark.parametrize("architecture", ["", "x86_64", "aarch64", "armhf", "i386", "AMD64"])
def test_unsupported_architectures_fail_before_mirror_or_package_mutation(architecture):
    with pytest.raises(ValueError, match="declared amd64 and arm64"):
        ci_apt.mirror_for_architecture(architecture)


@pytest.mark.parametrize(
    "github,runner,system",
    [
        ("false", "Linux", "Linux"),
        ("", "Linux", "Linux"),
        ("TRUE", "Linux", "Linux"),
        ("true", "macOS", "Linux"),
        ("true", "Linux", "Darwin"),
        ("true", "Linux", "Windows"),
    ],
)
def test_runner_guard_refuses_before_any_command_or_owned_file_write(
    owned_commands,
    monkeypatch,
    github,
    runner,
    system,
):
    original = ci_apt.MIRROR_FILE.read_bytes()
    monkeypatch.setenv("GITHUB_ACTIONS", github)
    monkeypatch.setenv("RUNNER_OS", runner)
    monkeypatch.setattr(ci_apt.platform, "system", lambda: system)
    with pytest.raises(ValueError, match="Linux GitHub Actions"):
        ci_apt.bootstrap(["tmux"])
    assert owned_commands.calls == [] and ci_apt.MIRROR_FILE.read_bytes() == original


@pytest.mark.parametrize(
    "packages",
    [
        [],
        ["--allow-unauthenticated"],
        ["--option"],
        ["xclip=1"],
        ["xclip:amd64"],
        ["../xclip"],
        ["xclip\n"],
        ["xclip xvfb"],
        ["install"],
        [""],
        ["curl"],
        ["tmux", "tmux"],
        [None],
        "xclip",
        b"xclip",
    ],
)
def test_package_list_refuses_options_overrides_unknowns_and_duplicates(owned_commands, packages):
    with pytest.raises(ValueError):
        ci_apt.bootstrap(packages)
    assert owned_commands.calls == []


@pytest.mark.parametrize("architecture", ["amd64", "arm64"])
def test_bounded_signed_update_and_noninteractive_install_preserve_exact_package_closure(
    owned_commands,
    architecture,
):
    owned_commands.architecture = (architecture + "\n").encode()
    if architecture == "arm64":
        ci_apt.MIRROR_FILE.write_text("http://ports.ubuntu.com/ubuntu-ports\n")
    packages = ["openssh-server", "tmux", "xclip", "xvfb", "gcc", "libc6-dev", "binutils"]
    ci_apt.bootstrap(packages)
    assert [phase for phase, _, _ in owned_commands.calls] == [
        "architecture",
        "mirror",
        "update",
        "install",
    ]
    assert ci_apt.MIRROR_FILE.read_text() == ci_apt.mirror_for_architecture(architecture) + "\n"
    assert [kwargs["timeout"] for _, _, kwargs in owned_commands.calls] == [10, 15, 130, 190]
    for phase, argv, kwargs in owned_commands.calls[1:]:
        assert argv[:6] == (
            "/usr/bin/sudo",
            "--non-interactive",
            "--",
            "/usr/bin/timeout",
            "--signal=TERM",
            "--kill-after=5s",
        )
        assert "--foreground" not in argv and "shell" not in kwargs
        assert argv[6] == {"mirror": "5s", "update": "120s", "install": "180s"}[phase]
    update, install = owned_commands.calls[2][1], owned_commands.calls[3][1]
    options = (
        "-o",
        "Acquire::Languages=none",
        "-o",
        "Acquire::Retries=1",
        "-o",
        "Acquire::http::Timeout=15",
        "-o",
        "Acquire::https::Timeout=15",
        "-o",
        "DPkg::Lock::Timeout=60",
    )
    assert update[7:] == ("/usr/bin/apt-get", *options, "update", "--error-on=any")
    assert install[7:] == (
        "/usr/bin/env",
        "DEBIAN_FRONTEND=noninteractive",
        "/usr/bin/apt-get",
        *options,
        "install",
        "--yes",
        "--",
        *packages,
    )
    assert "--no-install-recommends" not in install
    assert "APT::Acquire::Retries=1" not in update
    assert not any(
        "unauthenticated" in arg or "Verify-Peer" in arg or "AllowInsecure" in arg
        for _, argv, _ in owned_commands.calls
        for arg in argv
    )


@pytest.mark.parametrize(
    "output", [b"", b"amd64" + b" " * 33, b"\xff", b"armhf\n", b"amd64\narm64\n", None, "amd64\n"]
)
def test_invalid_or_oversized_dpkg_output_never_starts_sudo(owned_commands, output):
    original = ci_apt.MIRROR_FILE.read_bytes()
    owned_commands.architecture = output
    with pytest.raises(ValueError):
        ci_apt.bootstrap(["tmux"])
    assert len(owned_commands.calls) == 1 and ci_apt.MIRROR_FILE.read_bytes() == original


def test_missing_referenced_mirror_list_refuses_before_update_and_install(
    owned_commands,
    capsys,
):
    ci_apt.MIRROR_FILE.unlink()
    with pytest.raises(FileNotFoundError):
        ci_apt.bootstrap(["tmux"])
    assert [phase for phase, _, _ in owned_commands.calls] == ["architecture"]
    assert not ci_apt.MIRROR_FILE.exists()
    assert "retaining" not in capsys.readouterr().out


def test_actual_arm_source_without_mirror_file_reaches_signed_update_and_install(owned_commands):
    owned_commands.architecture = b"arm64\n"
    ci_apt.MIRROR_FILE.unlink()
    original = (
        "deb http://ports.ubuntu.com/ubuntu-ports jammy main restricted universe multiverse\n"
        "deb http://ports.ubuntu.com/ubuntu-ports jammy-security main restricted universe multiverse\n"
    )
    ci_apt.SOURCE_LIST.write_text(original)
    ci_apt.bootstrap(["gcc", "libc6-dev", "binutils"])
    assert ci_apt.SOURCE_LIST.read_text() == original.replace(
        "http://ports.ubuntu.com/ubuntu-ports", "https://mirrors.mit.edu/ubuntu-ports"
    )
    assert [phase for phase, _, _ in owned_commands.calls] == [
        "architecture",
        "mirror",
        "update",
        "install",
    ]
    assert not ci_apt.MIRROR_FILE.exists()


def test_late_invalid_source_refuses_before_any_source_write(owned_commands):
    original = ci_apt.MIRROR_FILE.read_bytes()
    (ci_apt.SOURCE_DIRECTORY / "later.sources").write_text(
        "Types: deb\nURIs: https://archive.ubuntu.com/ubuntu\nSuites: unknown\nComponents: main\n"
    )
    with pytest.raises(ValueError):
        ci_apt.bootstrap(["tmux"])
    assert len(owned_commands.calls) == 1 and ci_apt.MIRROR_FILE.read_bytes() == original


def test_source_changed_after_plan_refuses_before_tee_or_update(owned_commands, monkeypatch):
    original = ci_apt.MIRROR_FILE.read_bytes()
    monkeypatch.setattr(ci_apt, "source_bytes", lambda path: b"changed-source")
    with pytest.raises(ValueError, match="configuration changed"):
        ci_apt.bootstrap(["tmux"])
    assert len(owned_commands.calls) == 1 and ci_apt.MIRROR_FILE.read_bytes() == original


def test_later_changed_file_is_refused_before_writing_an_earlier_source(
    owned_commands, monkeypatch
):
    source = "deb http://archive.ubuntu.com/ubuntu noble main\n"
    ci_apt.SOURCE_LIST.write_text(source)
    (ci_apt.SOURCE_DIRECTORY / "ubuntu.sources").write_text(
        "Types: deb\nURIs: mirror+file:/etc/apt/apt-mirrors.txt\nSuites: noble\nComponents: main\n"
    )
    original_read = ci_apt.source_bytes
    monkeypatch.setattr(
        ci_apt,
        "source_bytes",
        lambda path: b"changed-source" if path == ci_apt.MIRROR_FILE else original_read(path),
    )
    with pytest.raises(ValueError, match="configuration changed"):
        ci_apt.bootstrap(["tmux"])
    assert len(owned_commands.calls) == 1 and ci_apt.SOURCE_LIST.read_text() == source


def test_unchanged_selected_mirror_needs_no_file_write(owned_commands):
    ci_apt.MIRROR_FILE.write_text("https://mirrors.mit.edu/ubuntu\n")
    ci_apt.bootstrap(["tmux"])
    assert [phase for phase, _, _ in owned_commands.calls] == ["architecture", "update", "install"]


@pytest.mark.parametrize("entry", ["symlink", "directory"])
def test_nonregular_mirror_list_is_refused_without_following_it(owned_commands, tmp_path, entry):
    ci_apt.MIRROR_FILE.unlink()
    target = tmp_path / "owned-unrelated-file"
    target.write_text("preserved")
    if entry == "symlink":
        ci_apt.MIRROR_FILE.symlink_to(target)
    else:
        ci_apt.MIRROR_FILE.mkdir()
    with pytest.raises(ValueError, match="symlink or nonregular"):
        ci_apt.bootstrap(["tmux"])
    assert len(owned_commands.calls) == 1 and target.read_text() == "preserved"


@pytest.mark.parametrize(
    "phase,index", [("architecture", 1), ("mirror", 2), ("update", 3), ("install", 4)]
)
@pytest.mark.parametrize(
    "failure",
    [
        subprocess.CalledProcessError(100, ("owned-fake-command",)),
        subprocess.TimeoutExpired(("owned-fake-command",), 1),
    ],
)
def test_each_command_failure_stops_without_success_or_automatic_replay(
    owned_commands,
    phase,
    index,
    failure,
):
    owned_commands.fail_phase, owned_commands.failure = phase, failure
    with pytest.raises(type(failure)) as observed:
        ci_apt.bootstrap(["tmux"])
    assert observed.value is failure and len(owned_commands.calls) == index


@pytest.mark.parametrize("mirror", ["http://archive.ubuntu.com/ubuntu", "https://" + "a" * 256])
def test_mirror_write_rejects_non_https_or_unbounded_selection(owned_commands, monkeypatch, mirror):
    monkeypatch.setitem(ci_apt.MIRRORS, "amd64", mirror)
    with pytest.raises(ValueError, match="bounded reviewed HTTPS"):
        ci_apt.bootstrap(["tmux"])
    assert len(owned_commands.calls) == 1


def test_cli_success_runs_declared_packages_without_extra_configuration(owned_commands):
    assert ci_apt.main(["xclip", "xvfb"]) == 0
    assert owned_commands.calls[-1][1][-2:] == ("xclip", "xvfb")


@pytest.mark.parametrize("arguments", [[], ["--allow-unauthenticated"], ["curl"]])
def test_cli_rejects_unknown_flags_and_packages_before_commands(owned_commands, arguments):
    with pytest.raises(SystemExit) as error:
        ci_apt.main(arguments)
    assert error.value.code == 2 and owned_commands.calls == []


@pytest.mark.parametrize("code,expected", [(100, 100), (124, 124), (-15, 1), (256, 1)])
def test_cli_preserves_nonzero_package_manager_or_timeout_exit(
    owned_commands, capsys, code, expected
):
    owned_commands.fail_phase = "update"
    owned_commands.failure = subprocess.CalledProcessError(code, ("owned-fake-command",))
    assert ci_apt.main(["tmux"]) == expected
    assert len(owned_commands.calls) == 3 and "bootstrap failed" in capsys.readouterr().err


@pytest.mark.parametrize(
    "failure",
    [OSError("synthetic-private-error"), subprocess.TimeoutExpired(("owned-fake-command",), 1)],
)
def test_cli_reports_preparation_and_outer_deadline_failure_as_failure(
    owned_commands, capsys, failure
):
    owned_commands.fail_phase, owned_commands.failure = "architecture", failure
    assert ci_apt.main(["tmux"]) == 1
    captured = capsys.readouterr().err
    assert "bootstrap failed" in captured and "synthetic-private-error" not in captured
    assert len(owned_commands.calls) == 1


def test_cli_outside_actions_refuses_without_commands(owned_commands, monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_ACTIONS")
    assert ci_apt.main(["tmux"]) == 1
    assert owned_commands.calls == [] and "bootstrap failed" in capsys.readouterr().err
