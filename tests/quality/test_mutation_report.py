"""Timeouts, missing mutants and malformed reports cannot masquerade as kills."""

import json

import pytest

from scripts.report_mutations import OUTCOMES, main, metadata_errors, report


def counts(**values):
    return {"total": 100, **dict.fromkeys(OUTCOMES, 0), "killed": 85, "survived": 15, **values}


@pytest.mark.parametrize("killed", [84, 85, 100])
def test_real_kills_define_the_reported_target_without_discounting_survivors(killed):
    result = report(counts(killed=killed, survived=100 - killed))
    assert result["kill_percentage"] == killed
    assert result["target_met"] is (killed >= 85)
    assert result["completed_without_tool_errors"]


@pytest.mark.parametrize("outcome", ["suspicious", "check_was_interrupted_by_user", "segfault"])
def test_tool_failures_never_count_as_kills_or_complete_evidence(outcome):
    result = report(counts(killed=84, **{outcome: 1}))
    assert result["kill_percentage"] == 84
    assert not result["target_met"] and not result["completed_without_tool_errors"]
    assert result["timeout_counts_as_killed"] is False


def test_terminal_mutant_timeout_is_a_warning_and_never_a_successful_kill():
    result = report(counts(survived=14, timeout=1))
    assert result["kill_percentage"] == 85 and result["target_met"]
    assert result["completed_without_tool_errors"] and result["timeout_review_required"]
    assert not result["clean_assertion_outcomes"]


def test_pytest_internal_errors_are_removed_from_kills_and_block_complete_evidence():
    result = report(counts(), internal_errors=1)
    assert result["kill_percentage"] == 84 and result["normal_test_failure_kills"] == 84
    assert result["pytest_internal_errors"] == 1
    assert not result["target_met"] and not result["completed_without_tool_errors"]
    for value in (-1, True, 86):
        with pytest.raises(ValueError):
            report(counts(), internal_errors=value)


def test_unassessed_and_untested_mutants_remain_in_the_denominator():
    unfinished = report(counts(killed=85, survived=10))
    assert unfinished["unassessed"] == 5 and not unfinished["target_met"]
    assert not unfinished["completed_without_tool_errors"]
    untested = report(counts(killed=80, survived=10, no_tests=5, skipped=5))
    assert untested["kill_percentage"] == 80 and not untested["target_met"]
    assert not untested["completed_without_tool_errors"]


def metadata(tmp_path, exits):
    directory = tmp_path / "mutants"
    path = directory / "src/owned.py.meta"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"exit_code_by_key": dict(enumerate(exits))}))
    return directory


def test_metadata_distinguishes_internal_errors_and_rejects_unknown_or_inconsistent_evidence(
    tmp_path,
):
    directory = metadata(tmp_path, [1] * 84 + [3] + [0] * 15)
    assert metadata_errors(directory, counts()) == 1
    directory = metadata(tmp_path, [1] * 85 + [None] * 15)
    assert metadata_errors(directory, counts(survived=0)) == 0
    with pytest.raises(ValueError):
        metadata_errors(directory, counts())
    directory = metadata(tmp_path, [True])
    with pytest.raises(ValueError):
        metadata_errors(directory, counts())
    (directory / "src/owned.py.meta").write_text("[]")
    with pytest.raises(ValueError):
        metadata_errors(directory, counts())


@pytest.mark.parametrize(
    "value", [[], {}, counts(total=0), counts(killed=True), counts(killed=-1), counts(total=99)]
)
def test_invalid_statistics_fail_instead_of_publishing_a_percentage(value):
    with pytest.raises(ValueError):
        report(value)


def test_cli_writes_the_actual_counts_and_rejects_incomplete_or_invalid_input(tmp_path, capsys):
    source, output = tmp_path / "input.json", tmp_path / "output/report.json"
    source.write_text(json.dumps(counts()))
    directory = metadata(tmp_path, [1] * 85 + [0] * 15)
    arguments = [str(source), str(output), "--metadata", str(directory)]
    assert main(arguments) == 0
    assert json.loads(output.read_text())["counts"]["killed"] == 85
    source.write_text(json.dumps(counts(survived=10)))
    metadata(tmp_path, [1] * 85 + [0] * 10 + [None] * 5)
    assert main(arguments) == 1
    source.write_text("invalid JSON")
    with pytest.raises(SystemExit) as error:
        main(arguments)
    assert error.value.code == 1 and "failed" in capsys.readouterr().err
