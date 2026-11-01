"""Namespace-aware protection against test dependencies on application internals."""

from pathlib import Path

import pytest

from scripts.check_private_access import main, violations


def project(root: Path, source: str) -> Path:
    application = root / "src/kuberich/ui/app.py"
    application.parent.mkdir(parents=True)
    application.write_text(
        """
class Child:
    def __init__(self):
        self._pending = None

class KubeRichApp:
    def __init__(self):
        self._secret = None
        self.child = Child()

    def _dispatch(self):
        pass

    @property
    def state(self) -> str:
        return "ready"

def build() -> KubeRichApp:
    return KubeRichApp()
""",
        encoding="utf-8",
    )
    tests = root / "tests"
    tests.mkdir()
    path = tests / "test_example.py"
    path.write_text(source, encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("source", "member"),
    [
        ("from kuberich.ui.app import KubeRichApp\napp=KubeRichApp()\napp._secret", "_secret"),
        ("import kuberich.ui.app as ui\nui.KubeRichApp()._dispatch()", "_dispatch"),
        ("import kuberich.ui.app\nkuberich.ui.app.KubeRichApp()._secret", "_secret"),
        (
            "from kuberich.ui.app import KubeRichApp as App\nother=App()\nalias=other\nalias._secret",
            "_secret",
        ),
        ("from kuberich.ui.app import build\napp=build()\napp.child._pending", "_pending"),
        (
            "from kuberich.ui.app import KubeRichApp\ndef trial(app: KubeRichApp):\n return app._secret",
            "_secret",
        ),
        (
            "from kuberich.ui.app import KubeRichApp\ndef trial(app: 'KubeRichApp'):\n return app._secret",
            "_secret",
        ),
        (
            "from kuberich.ui.app import KubeRichApp\napp=KubeRichApp()\ngetattr(app,'_secret')",
            "_secret",
        ),
        (
            "from kuberich.ui.app import KubeRichApp\napp=KubeRichApp()\nmember='_'+'secret'\ngetattr(app,member)",
            "_secret",
        ),
        (
            "from kuberich.ui.app import KubeRichApp\nfrom builtins import setattr as assign\nassign(KubeRichApp(),'_secret',0)",
            "_secret",
        ),
        (
            "from kuberich.ui.app import KubeRichApp\ndef trial(monkeypatch):\n monkeypatch.setattr(KubeRichApp(),'_dispatch',None)",
            "_dispatch",
        ),
        (
            "def trial(monkeypatch):\n monkeypatch.setattr('kuberich.ui.app.KubeRichApp._secret',None)",
            "_secret",
        ),
        (
            "from unittest.mock import patch\npatch('kuberich.ui.app.KubeRichApp._dispatch')",
            "_dispatch",
        ),
        ("from kuberich.ui.app import _dispatch as public_name", "_dispatch"),
        ("import kuberich.ui._hidden as public_name", "_hidden"),
        ("from kuberich.ui._hidden import public_name", "_hidden"),
        (
            "from importlib import import_module\nmodule=import_module('kuberich.ui.app')\nmodule._dispatch",
            "_dispatch",
        ),
    ],
)
def test_rejects_owned_private_accesses_and_imports(
    tmp_path: Path, source: str, member: str
) -> None:
    path = project(tmp_path, source)
    results = violations(tmp_path)
    assert results
    assert {finding.member for finding in results} == {member}
    assert {finding.path for finding in results} == {path}
    assert all(finding.line > 0 and finding.column > 0 for finding in results)


def test_tracks_imported_test_factories_and_untyped_helper_arguments(tmp_path: Path) -> None:
    project(
        tmp_path,
        """
from tests.factories import make_app

def check(app):
    return app._secret

def test_behavior():
    app = make_app()
    check(app)
""",
    )
    (tmp_path / "tests/factories.py").write_text(
        "from kuberich.ui.app import build\ndef make_app():\n return build()\n",
        encoding="utf-8",
    )
    assert [finding.member for finding in violations(tmp_path)] == ["_secret"]


def test_untyped_keyword_argument_cannot_hide_an_owned_helper_parameter(tmp_path: Path) -> None:
    project(
        tmp_path,
        "from kuberich.ui.app import KubeRichApp\ndef check(app):\n return app._secret\ndef test_example():\n check(app=KubeRichApp())\n",
    )
    assert [finding.member for finding in violations(tmp_path)] == ["_secret"]


@pytest.mark.parametrize("container", ["[KubeRichApp()]", "{'owned':KubeRichApp()}"])
def test_runtime_container_aliases_keep_owned_element_provenance(
    tmp_path: Path, container: str
) -> None:
    index = "0" if container.startswith("[") else "'owned'"
    project(
        tmp_path,
        f"from kuberich.ui.app import KubeRichApp\nitems={container}\nalias=items\nalias[{index}]._secret\n",
    )
    assert [finding.member for finding in violations(tmp_path)] == ["_secret"]


@pytest.mark.parametrize("factory", ["App", "Fake"])
def test_runtime_foreign_and_test_double_containers_remain_separate(
    tmp_path: Path, factory: str
) -> None:
    project(
        tmp_path,
        f"from textual.app import App\nclass Fake:\n _secret=None\nitems=[{factory}()]\nitems[0]._secret\nmapping={{'owned':{factory}()}}\nmapping['owned']._secret\n",
    )
    assert violations(tmp_path) == []


@pytest.mark.parametrize("target", ["KubeRichApp", "App", "Fake"])
def test_patch_object_resolves_target_namespace_before_rejecting_private_members(
    tmp_path: Path, target: str
) -> None:
    project(
        tmp_path,
        f"from unittest.mock import patch as replace\nfrom kuberich.ui.app import KubeRichApp\nfrom textual.app import App\nclass Fake:\n _secret=None\nreplace.object({target},'_secret',None)\n",
    )
    assert [finding.member for finding in violations(tmp_path)] == (
        ["_secret"] if target == "KubeRichApp" else []
    )


def test_nested_helpers_keep_owned_outer_values(tmp_path: Path) -> None:
    project(
        tmp_path,
        """
from kuberich.ui.app import KubeRichApp
def test_example():
    app = KubeRichApp()
    async def delayed():
        return app._secret
""",
    )
    assert [finding.member for finding in violations(tmp_path)] == ["_secret"]


def test_async_contextmanager_and_iteration_aliases_preserve_ownership(tmp_path: Path) -> None:
    project(
        tmp_path,
        """
from contextlib import asynccontextmanager
from kuberich.ui.app import KubeRichApp

@asynccontextmanager
async def owner():
    yield KubeRichApp()

async def test_example():
    async with owner() as runner:
        runner._secret
    for screen in [KubeRichApp()]:
        screen._dispatch()
""",
    )
    assert [finding.member for finding in violations(tmp_path)] == ["_secret", "_dispatch"]


def test_pytest_fixture_owner_is_resolved_from_conftest(tmp_path: Path) -> None:
    project(tmp_path, "def test_example(app):\n return app._secret\n")
    (tmp_path / "tests/conftest.py").write_text(
        "import pytest\nfrom kuberich.ui.app import KubeRichApp\n@pytest.fixture\ndef app():\n return KubeRichApp()\n",
        encoding="utf-8",
    )
    assert [finding.member for finding in violations(tmp_path)] == ["_secret"]


def test_parametrized_constructor_is_not_an_untyped_escape(tmp_path: Path) -> None:
    project(
        tmp_path,
        "import pytest\nfrom kuberich.ui.app import KubeRichApp\n@pytest.mark.parametrize('factory',[pytest.param(KubeRichApp,id='owned')])\ndef test_example(factory):\n return factory()._secret\n",
    )
    assert [finding.member for finding in violations(tmp_path)] == ["_secret"]


def test_conditional_branches_retain_possible_owned_values(tmp_path: Path) -> None:
    project(
        tmp_path,
        """
from kuberich.ui.app import KubeRichApp
class Fake:
    _secret = None
def test_example(flag):
    if flag:
        value = KubeRichApp()
    else:
        value = Fake()
    value._secret
""",
    )
    assert [finding.member for finding in violations(tmp_path)] == ["_secret"]


def test_subclass_inheritance_is_owned_but_test_local_fields_are_not(tmp_path: Path) -> None:
    project(
        tmp_path,
        """
from kuberich.ui.app import KubeRichApp
class Trial(KubeRichApp):
    def __init__(self):
        super().__init__()
        self._test_marker = None
    def dispatch(self):
        super()._dispatch()
        return self._test_marker
def test_example():
    value = Trial()
    value._secret
    value._test_marker
""",
    )
    assert [finding.member for finding in violations(tmp_path)] == ["_dispatch", "_secret"]


def test_top_level_terminal_program_is_checked_with_source_line_location(tmp_path: Path) -> None:
    path = project(
        tmp_path,
        'PROGRAM = """\nfrom kuberich.ui.app import KubeRichApp\napp=KubeRichApp()\napp._secret\n"""\n',
    )
    result = violations(tmp_path)
    assert len(result) == 1
    assert result[0].path == path
    assert result[0].line == 4
    assert result[0].member == "_secret"


def test_embedded_terminal_subclass_does_not_hide_private_parent_calls(tmp_path: Path) -> None:
    project(
        tmp_path,
        'PROGRAM = """\nfrom kuberich.ui.app import KubeRichApp\nclass Trial(KubeRichApp):\n def observe(self):\n  return super()._dispatch()\n"""\n',
    )
    assert [finding.member for finding in violations(tmp_path)] == ["_dispatch"]


def test_foreign_namespaces_local_doubles_and_fixture_strings_are_not_owned(tmp_path: Path) -> None:
    project(
        tmp_path,
        """
import sys
from asyncio import Task
from textual.app import App
from kuberich.ui.app import KubeRichApp

class Fake:
    _secret = 3

def test_example():
    app = Fake()
    app._secret
    foreign = App()
    foreign._exit
    sys._getframe()
    Task._state
    text = "from kuberich.ui.app import KubeRichApp\\nKubeRichApp()._secret"
    app = KubeRichApp()
    app.state
    app.__class__
    raw = '\\ud800'
""",
    )
    assert violations(tmp_path) == []


def test_local_shadowing_does_not_make_a_fake_into_an_imported_application(tmp_path: Path) -> None:
    project(
        tmp_path,
        """
from kuberich.ui.app import KubeRichApp as App
def test_example():
    class App:
        _pending = 1
    app = App()
    return app._pending
""",
    )
    assert violations(tmp_path) == []


def test_cli_returns_nonzero_with_a_concrete_source_diagnostic(tmp_path: Path, capsys) -> None:
    path = project(tmp_path, "from kuberich.ui.app import KubeRichApp\nKubeRichApp()._secret\n")
    assert main(["--root", str(tmp_path)]) == 1
    output = capsys.readouterr().out
    assert str(path) + ":2:1:" in output
    assert "_secret" in output and "1 violation(s)" in output
    path.write_text("from kuberich.ui.app import KubeRichApp\nKubeRichApp().state\n")
    assert main(["--root", str(tmp_path)]) == 0
    assert capsys.readouterr().out == "Private-access check passed.\n"


def test_syntax_errors_fail_closed_instead_of_omitting_a_test(tmp_path: Path) -> None:
    project(tmp_path, "def invalid syntax")
    with pytest.raises(SyntaxError):
        violations(tmp_path)


def test_missing_repository_directories_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="requires directory"):
        violations(tmp_path)
