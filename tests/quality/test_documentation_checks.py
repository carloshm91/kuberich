"""Real source contracts fail; editorial and public-link observations are advisory."""

import json
import subprocess
import time

import pytest

from scripts import check_documentation, documentation_external
from scripts.build_site import build
from scripts.check_documentation import ROOT, avoid_words, check, observations
from scripts.check_site import verify
from scripts.documentation_external import display_url, probe_https, probe_links
from tests.support.site_source import copy_source


def test_report_checks_the_real_declarations_navigation_and_repository_links():
    report = check(ROOT)
    assert report["functional_checks_passed"] is True
    assert report["canonical_user_pages"] == 24
    assert report["local_markdown_links"] > 500
    assert isinstance(report["editorial_advisories"], list)
    assert report["external_links"] == []


def test_added_contributor_line_reports_do_not_expand_external_probes(monkeypatch):
    expected = set()
    catalog = check_documentation.load_navigation(ROOT)
    sources = {
        ROOT / "docs" / name for page in catalog.pages for name in (page.source, *page.sources)
    } | {ROOT / "README.md"}
    for path in sources:
        expected.update(observations(path.relative_to(ROOT).as_posix(), path.read_text(), {})[1])
    probed = []

    def observe_probes(urls):
        probed.extend(urls)
        return []

    monkeypatch.setattr(check_documentation, "probe_links", observe_probes)
    assert check(ROOT, external=True)["functional_checks_passed"] is True
    assert set(probed) == expected


def test_editorial_findings_use_the_current_style_table_and_skip_code_literals(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/STYLE.md").write_text("| Avoid | Prefer |\n| owned | created here |\n")
    words = avoid_words(tmp_path)
    findings, links = observations(
        "docs/task.md",
        "# Task\n\n### Owned resources\n\n"
        "Use `owned` unchanged in code.\n\n"
        "```\nowned=1\n```\n\n"
        "[Reference](https://docs.python.org/3/?mode=docs#heading) \n",
        words,
    )
    assert words == {"owned": "created here"}
    assert [item["line"] for item in findings if item["rule"] == "plain-language"] == [3]
    assert {item["rule"] for item in findings} == {
        "heading-level",
        "plain-language",
        "fence-language",
        "trailing-space",
    }
    assert links == {"https://docs.python.org/3/?mode=docs"}
    assert not observations("docs/task.md", "# Task\n\nUse `owned`.\n", words)[0]


def test_advisory_page_length_and_final_newline_do_not_hide_the_source_location():
    findings, _ = observations("docs/task.md", "# Task\n" + "line\n" * 250 + "last", {})
    assert {(item["rule"], item["line"]) for item in findings} == {
        ("page-length", 251),
        ("final-newline", 252),
    }
    assert all(item["severity"] == "advisory" for item in findings)


def test_long_user_prose_and_banned_word_are_reported_but_do_not_break_a_correct_site(tmp_path):
    source = copy_source(tmp_path / "source")
    quickstart = source / "docs/quickstart.md"
    text = (
        quickstart.read_text()
        + "\nThese owned resources are a wording example.\n"
        + "More details.\n" * 251
    )
    quickstart.write_text(text)
    findings, _ = observations("docs/quickstart.md", text, avoid_words(ROOT))
    assert {"plain-language", "page-length"} <= {item["rule"] for item in findings}
    assert all(item["severity"] == "advisory" for item in findings)
    output = tmp_path / "output"
    assert build(output, source)["documentation_pages"] == 24
    assert verify(output, source)["pages"] > 20
    assert "These owned resources" in (output / "docs/quickstart.html").read_text()


def test_contributor_line_target_is_reported_as_an_advisory():
    findings, _ = observations("CONTRIBUTING.md", "# Contribute\n" + "Details.\n" * 151, {})
    assert findings == [
        {
            "file": "CONTRIBUTING.md",
            "line": 151,
            "rule": "page-length",
            "message": "Consider a shorter page (150-line guidance)",
            "severity": "advisory",
        }
    ]


def test_cli_reports_real_source_errors_and_returns_failure(tmp_path, monkeypatch):
    def missing_reference(root):
        raise ValueError("Generated CLI reference differs from current declarations")

    monkeypatch.setattr(check_documentation, "check_reference_files", missing_reference)
    report = tmp_path / "report.json"
    monkeypatch.setattr("sys.argv", ["check-documentation", "--report", str(report)])
    assert check_documentation.main() == 1
    assert json.loads(report.read_text()) == {
        "functional_checks_passed": False,
        "error": "Generated CLI reference differs from current declarations",
    }


def test_cli_keeps_editorial_and_network_observations_advisory(tmp_path, monkeypatch):
    report = tmp_path / "report.json"
    value = {
        "functional_checks_passed": True,
        "editorial_advisories": [{"rule": "page-length"}],
        "external_links": [{"status": "unavailable"}],
    }
    monkeypatch.setattr(check_documentation, "check", lambda *args, **kwargs: value)
    monkeypatch.setattr("sys.argv", ["check-documentation", "--external", "--report", str(report)])
    assert check_documentation.main() == 0
    assert json.loads(report.read_text()) == value


@pytest.mark.parametrize(
    "url",
    [
        "http://docs.python.org/3/",
        "https://127.0.0.1/private",
        "https://[::1]/",
        "https://169.254.169.254/",
        "https://fixture.example.net/",
        "https://fixture.test/",
        "https://demo.svc.cluster.local/",
        "https://docs.internal/",
        "https://localhost/",
        "https://docs.python.org:8443/",
        "https://user:secret@docs.python.org/",
        "file:///etc/hosts",
        "https://docs.python.org./",
        "https://docs.invalid/",
    ],
)
def test_external_probe_excludes_fixture_private_and_non_https_urls_before_dns(url):
    def forbidden(command, timeout):
        pytest.fail("Excluded endpoint must never start a DNS or HTTP child")

    result = probe_https(url, time.monotonic() + 10, execute=forbidden, curl="curl")
    assert result["status"] == "excluded"
    assert "secret" not in json.dumps(result)


@pytest.mark.parametrize(
    "addresses",
    [
        ["127.0.0.1"],
        ["169.254.169.254"],
        ["10.0.0.1"],
        ["192.0.2.1"],
        ["224.0.0.1"],
        ["8.8.8.8", "127.0.0.1"],
        [1],
    ],
)
def test_mixed_private_reserved_and_invalid_dns_answers_never_reach_http(addresses):
    calls = []

    def execute(command, timeout):
        calls.append(command)
        assert command[1:3] == ["-I", "-S"]
        return subprocess.CompletedProcess(command, 0, json.dumps(addresses))

    result = probe_https(
        "https://docs.python.org/3/", time.monotonic() + 10, execute=execute, curl="curl"
    )
    assert result["status"] == "excluded" and len(calls) == 1


@pytest.mark.parametrize(
    ("code", "expected"),
    [("200", "reachable"), ("302", "review"), ("404", "review"), ("405", "review")],
)
def test_https_probe_pins_public_address_and_does_not_follow_redirects(code, expected):
    calls = []

    def execute(command, timeout):
        calls.append((command, timeout))
        if len(calls) == 1:
            return subprocess.CompletedProcess(command, 0, '["8.8.8.8"]')
        assert command[1] == "--disable" and "--head" in command
        assert "--location" not in command and "-L" not in command
        assert command[command.index("--resolve") + 1] == "docs.python.org:443:8.8.8.8"
        assert command[command.index("--proto") + 1] == "=https"
        assert command[command.index("--noproxy") + 1] == "*"
        assert "--output" in command and timeout <= 4
        return subprocess.CompletedProcess(command, 0, code)

    result = probe_https(
        "https://docs.python.org/3/?value=hidden",
        time.monotonic() + 10,
        execute=execute,
        curl="curl",
    )
    assert result["status"] == expected and result["http_status"] == int(code)
    assert result["url"] == "https://docs.python.org/3/" and len(calls) == 2


@pytest.mark.parametrize("failure", ["timeout", "oserror", "dns", "json", "http"])
def test_probe_failure_is_an_advisory_with_no_raw_error_or_body(failure):
    calls = []

    def execute(command, timeout):
        calls.append(command)
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, timeout, output="private error")
        if failure == "oserror":
            raise OSError("private error")
        if len(calls) == 1:
            if failure == "dns":
                return subprocess.CompletedProcess(command, 1, "private error")
            return subprocess.CompletedProcess(
                command, 0, "not JSON" if failure == "json" else '["8.8.8.8"]'
            )
        return subprocess.CompletedProcess(command, 1, "private error")

    result = probe_https(
        "https://docs.python.org/3/", time.monotonic() + 10, execute=execute, curl="curl"
    )
    assert result["status"] == "unavailable" and "private error" not in json.dumps(result)


def test_expired_report_budget_starts_no_child():
    def forbidden(command, timeout):
        pytest.fail("Expired report cannot start another child")

    assert (
        probe_https("https://docs.python.org/3/", 0, execute=forbidden)["status"] == "not checked"
    )


def test_report_has_a_fixed_unique_url_limit_and_redacts_excess_targets(monkeypatch):
    calls = []

    def probe(url, deadline):
        calls.append((url, deadline))
        return {"url": display_url(url), "status": "review"}

    monkeypatch.setattr(documentation_external, "probe_https", probe)
    urls = [f"https://docs.python.org/{index:03}/?secret=hidden" for index in range(66)]
    results = probe_links([*urls, urls[0]])
    assert len(calls) == 64 and len(results) == 66
    assert len({deadline for _, deadline in calls}) == 1
    assert all(result["status"] == "not checked" for result in results[64:])
    assert "hidden" not in json.dumps(results)


def test_existing_repository_job_keeps_required_source_checks_and_saves_report():
    workflow = (ROOT / ".github/workflows/repository.yml").read_text()
    assert "uv run python -m scripts.validate_plan" in workflow
    assert "uv run python -m scripts.check_documentation --external" in workflow
    assert "artifacts/site-qa/documentation-report.json" in workflow
    assert "uv run python -m scripts.check_site" in workflow
    assert "continue-on-error" not in workflow
