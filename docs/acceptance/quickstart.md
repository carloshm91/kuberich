# W01 #39 installed first-user guide

The current [quickstart](../quickstart.md) documents the usable development
preview and the exact boundaries of the first release. It includes explicit
context/kubeconfig/namespace selection, read-only and invocation-only write
overrides, declared EKS/AKS helper prerequisites, navigation, logs, embedded
shell return/quit, local installation/uninstallation and troubleshooting.

## Actual Linux rehearsal

The initial owned trial installed a real `0.0.1.dev0` wheel with SHA-256
`44a1bbffdb37cbc804dccabc731d66ece1de4820a2eac20490c7888193a6e545`
using uv 0.10.4 and CPython 3.12.12, outside the source checkout. It passed
version/help/config/info, context-alias switching, namespace filtering and
Enter-to-pods, pod details/YAML/events, container logs, read-only shell refusal,
`--write` overriding a read-only preference, embedded shell commands, repeated
shell exit/Ctrl+] return, Ctrl+Q and terminal restoration, and uninstallation
with preferences preserved. Context aliases point to the same owned cluster;
this is not a claim of real multi-provider certification.

The verifier uses pinned kind 0.33.0, Kubernetes/kubectl 1.36.4 and the Alpine
fixture digest from [integration qualification](../integration-testing.md).
It creates and verifies its own Docker node/API endpoint before fixture writes,
uses its generated kubeconfig explicitly, and verifies deletion afterward.
Installer state, HOME, preferences and both terminal sessions are private
temporary directories; no maintainer cluster or existing tool installation is
used. Raw results are retained in `/tmp/kubetrol-39-evidence`.

Early failed harness attempts are retained separately. They showed that a
namespace name already in the header was insufficient evidence that rows had
loaded, details could exceed the visible viewport, and adjacent Escape/Enter
bytes could form Alt+Enter. The final driver waits for actual rows and completed
screen transitions; these failed attempts are not counted as successful trials.

## Frozen implementation and measured results

Initial frozen implementation: `896d481892de27a47373e2342aa0a87695032356`; base
`78c38426e207cb312611a7d373d31ebadf0d7f5c`. The only application change corrects
CLI help from native to embedded container shells. The shell image digest is
shared by the two owned verifiers; terminal-transport typing is clarified.

The repeated frozen-source development-wheel trial passed with SHA-256
`9316e02ab36c7e304701a69a3b8b8e48f9259c083fe34c3476ee3163c45dcf26`.
The audited canonical RC fixture at
`23130f9e03ec5c2eef61bbd9175da9903138ffd4` also passed the same installed
rehearsal with `0.0.1rc1` wheel SHA-256
`f8e1f3260737c7f734bb5d5d867034795bcdd7d14339fcc8058a04672d359d28`.
Both read-only/write sessions exited 0, restored terminal modes/cursor,
closed the alternate screen and disabled reporting modes. The canonical RC
is an owned local source fixture, not a tag/release on the project repository.

CPython 3.13.12 passed 847 affected quality/contract/packaging/CLI tests in
414.01 seconds; CPython 3.14.3 passed the same 847 in 417.50 seconds. Both passed
Ruff/format, strict 84-file types and provider types, plan validation,
build/Twine and installed-runtime audits for 27 locked/fresh dependencies with
no accepted exceptions. These are targeted runs, not newly measured full-source
coverage on those minors. Artifact directories were cleaned before these runs.
The focused CLI/owned-lifecycle suite passed 36 tests in 18.09 seconds.

The initial complete Python 3.12 run stopped after 1,624 passes with one
failure: its reviewable help snapshot still expected “native container shells”.
Both Python-specific snapshots now expect the implemented embedded shell text.
The tests-only follow-up is `2db1d83f6ae116ed08fe7a718b6ad074ee117bb7`;
application/scripts/workflow trees and every pinned release/security input remain
identical. The failed run and its transcript are preserved.

A fresh run of all **1,754 unit/contract/UI cases** passed on that follow-up in
656.19 seconds. It measures the entire production package, including unimported
modules: lines **6419/6451 (99.50%)**, branches **1891/1936 (97.68%)**; all 29
critical modules have 100% lines and applicable branches. Changed executable
production lines are N/A (0): the help literal is not a separate executable line
in the coverage diff. No source/module exclusions were added.

The other 520 unchanged quality/packaging/real-terminal cases already passed in
the preserved initial run. Together these qualify all **2,274 unique suite
cases**, rather than claiming a single clean full-suite rerun. Python 3.13/3.14
also each passed all 1,108 unit tests after the snapshot correction (7.63/7.45
seconds); with their earlier 847-case runs, each qualifies 1,946 unique cases.
They do not claim fresh complete-source coverage or a full terminal/UI run.

Final Ruff/format, strict types, plan/link checks, rebuilt artifacts/Twine,
independent coverage gates and installed-runtime security verification passed.
The rebuilt wheel/sdist bytes match the audited originals; all 13 security input
digests remain identical. Security provenance retains its actual original source
commit instead of relabeling it. The evidence/documentation-only completion
preserves those tested trees and inputs. Raw commands, results, failed attempts,
coverage, installation/terminal evidence and digests remain under
`/tmp/kubetrol-39-evidence`.

## Limits

 Actual macOS and public PyPI/Homebrew installation remain D04
#40. Real EKS/AKS remain Q05 #87. No package, tap, release tag or website is
published by this work. Automated coverage and the owned rehearsal do not
guarantee every cluster, provider, image or terminal.
