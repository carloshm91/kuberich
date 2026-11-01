"""UI ownership permits a class's internals while rejecting cross-controller access."""

from pathlib import Path

import pytest

from scripts.check_ui_boundaries import main, violations


def project(root: Path, consumer: str) -> Path:
    source = root / "src/kuberich/ui"
    source.mkdir(parents=True)
    (root / "tests").mkdir()
    (source / "owned.py").write_text(
        """
class Owned:
    def __init__(self):
        self._secret = 1

    def _change(self):
        return self._secret

    @property
    def state(self):
        return self._secret

def build() -> Owned:
    return Owned()

def _private():
    return None
""",
        encoding="utf-8",
    )
    path = source / "consumer.py"
    path.write_text(consumer, encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "source",
    [
        "from kuberich.ui.owned import Owned\nOwned()._secret",
        "from kuberich.ui.owned import Owned as Owner\nitem=Owner()\nalias=item\nalias._change()",
        "from kuberich.ui.owned import Owned\nclass Consumer:\n def __init__(self):\n  self.owner=Owned()\n def run(self):\n  return self.owner._secret",
        "from kuberich.ui.owned import build\ngetattr(build(), '_'+'secret')",
        "from kuberich.ui.owned import Owned\nfrom unittest.mock import patch\npatch.object(Owned, '_change', None)",
        "from kuberich.ui.owned import Owned\nitems=[Owned()]\nitems[0]._secret",
        "from kuberich.ui.owned import _private\n_private()",
        "from kuberich.ui.owned import Owned\ndef consume(owner: Owned):\n return owner._secret",
        "from kuberich.ui.owned import Owned\nclass Consumer(Owned):\n def run(self, other: Owned):\n  return super(Consumer, other)._secret",
    ],
)
def test_ui_guard_rejects_private_access_through_real_owned_provenance(tmp_path, source):
    path = project(tmp_path, source)
    findings = violations(tmp_path)
    assert findings and all(finding.path == path for finding in findings)


def test_ui_guard_preserves_own_class_closures_public_ports_and_separate_framework_ownership(
    tmp_path,
):
    project(
        tmp_path,
        """
from kuberich.ui.owned import Owned
from textual.screen import Screen

class Consumer:
    def __init__(self):
        self._pending = None
        self.owner = Owned()

    def run(self):
        alias = self
        def closure():
            return alias._pending
        return self.owner.state, closure()

def third_party(screen: Screen):
    return screen._framework_owned

class Derived(Owned):
    def run(self):
        return super()._change()
""",
    )
    assert violations(tmp_path) == []
    assert main(["--root", str(tmp_path)]) == 0


def test_ui_guard_cli_returns_failure_without_suppressions(tmp_path, capsys):
    path = project(tmp_path, "from kuberich.ui.owned import Owned\nOwned()._secret")
    assert main(["--root", str(tmp_path)]) == 1
    output = capsys.readouterr().out
    assert str(path) in output and "_secret" in output and "failed" in output
