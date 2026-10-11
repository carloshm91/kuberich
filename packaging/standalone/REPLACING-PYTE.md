# Replacing the terminal library

KubeRich includes the original Pyte 0.8.2 Python sources under `_internal/pyte`.
Their LGPL-3.0-only license and contributor notices are retained in
`THIRD-PARTY-NOTICES/pyte`. The frozen importer loads these source files directly;
it does not keep a second bytecode copy of Pyte in the embedded module archive.

To use your own compatible library changes, copy this entire application folder
to a location you own, modify or replace `_internal/pyte`, and launch `kuberich`
from that copy. Keep the package name and public interface compatible. No rebuild
of the application or removal of system security settings is required. Local
changes intentionally differ from the publisher's original archive checksum.

Reverse engineering the combined application to debug modifications of this
library is permitted. KubeRich's independent application source remains under
Apache-2.0. Build inputs, dependency versions and original file hashes are in the
associated native build manifest; the corresponding KubeRich source and frozen
build recipe are available at its recorded Git commit.
