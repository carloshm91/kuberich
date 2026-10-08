# B05 #41 acceptance evidence

The implementation adds 15 discovered standard resource tables. It shares the
existing session/list-watch/inspection ownership contracts and uses a single
widget with resource-specific columns. No mutation action is advertised.

| Acceptance | Verification |
| --- | --- |
| Each advertised endpoint, scope and typed columns | Parameterized registry and group-aware projection contracts; every family runs real discovery/LIST/WATCH/GET through Pilot |
| Typed numeric/time ordering, unknowns | Counts versus lexical order; binary/decimal storage quantities; timezone-aware instants; unknowns last both directions |
| Safe ordinary views | ConfigMap/Secret rows contain only counts/type; payloads excluded from filters and redacted on GET/YAML |
| Supported actions and unavailable APIs | Per-view shortcuts; Enter details; pod-only logs; absent and denied API failures followed by successful navigation |
| Stable responsive tables | Bounded patches, generation invalidation, UID replacement/deletion, scroll anchors, sorting, age updates, retained history, 40×12 and 100×30 layouts |
| Real Kubernetes | Owned kind fixtures for all 15 families, actual annotation changes arriving through WATCH, UID preserved and individual YAML GETs |
| Actual terminal/install | Source and freshly installed console/module PTYs, initial scoped command, workload/service/storage/Secret navigation, resize and terminal restoration |

Initial measured Linux/Python 3.12.12 evidence:

- Registry semantic suite: 109 passing cases, all 143 statements and 32 branches
  covered (100% independently). The module joins the enforced critical inventory.
- All-resource Pilot suite: 20 passing cases, including absent/denied APIs,
  namespace/all-scope commands, history and context return.
- `uv run python -m scripts.verify_contexts_kind --kind /tmp/kubetrol-tools/kind --evidence /tmp/kubetrol-41-evidence/kind-final.json`
  passed against kind 0.33.0 / pinned Kubernetes 1.36.4. The generated endpoint/node
  was verified before writes and the owned cluster was removed after success.
  The retained JSON contains each family's real LIST/WATCH/GET result.

The first fixture runs exposed a malformed synthetic pod watch, a test constructor
argument error and an SDK response-map mismatch in the verifier; those failures
were retained and corrected. They are not counted as successful verification.
Complete-suite, installed-package and final coverage evidence is recorded below
when delivery checks finish. Hosted Actions and new macOS qualification remain
unavailable under the account billing restriction; these local checks do not
replace the full public-release matrix.

Remaining behavior is explicitly tracked: resource mutations #43–#46, generic
CRD/server columns #53, broader drill-down/navigation #61, ephemeral containers
#78, metrics #68 and real cloud/provider certification #87. No release or public
distribution artifact is published by this issue.
