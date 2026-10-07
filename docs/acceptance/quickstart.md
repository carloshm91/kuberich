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

## Qualification status

Final frozen-source matrix and candidate rehearsal results will be recorded
before merging. Actual macOS and public PyPI/Homebrew installation remain D04
#40. Real EKS/AKS remain Q05 #87. No package, tap, release tag or website is
published by this work. Automated coverage and the owned rehearsal do not
guarantee every cluster, provider, image or terminal.
