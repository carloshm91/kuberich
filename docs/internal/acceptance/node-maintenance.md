# Node maintenance acceptance

Issue: [A02 #77](https://github.com/carloshm91/kuberich/issues/77).
Phase: v0.5.0. Implementation starts from
`7c8c7cb1595a3609c2d6a5748087d53917ce9af8` on `feat/77-node-maintenance`.
This record separates prepared contracts from measured behavior; preparation
does not establish delivery, hosted qualification or publication.

## Boundary

One actual core/v1 Node is captured with its session generation, UID and opaque
version. Reviews and one-use confirmation authorize cordon, fixed-set drain or
separate uncordon. Drain uses policy/v1 eviction with both Pod UID and version
preconditions. Unmanaged and emptyDir consents are independent; DaemonSet and
mirror/static Pods remain. Only explicitly refused 429 attempts can retry under
a finite deadline. Accepted/uncertain writes are not replayed. Cancellation stops
new requests without rollback, and a final read separately observes scheduling.

The same-Node read and Pod eviction are separate requests, not a transaction.
Controller identity, PDB status and declared storage do not guarantee workload
health, replacement capacity or storage portability. Pod version churn requires
a fresh review. Cloud/provider certification remains Q05 #87.

## Focused preparation checks

Run from the issue checkout:

```sh
uv run pytest tests/quality/test_owned_kind.py -q --basetemp=/tmp/kuberich-77-proof-03
uv run pytest tests/quality/test_node_maintenance_kind.py -q --basetemp=/tmp/kuberich-77-proof-02
uv run mypy --strict scripts/owned_kind.py scripts/verify_node_maintenance_kind.py scripts/qualification.py
```

The helper cohort passes 72 tests in 60.10 seconds with a fresh outside-checkout
temporary directory. The proof controller passes ten tests in 0.60 seconds.
Strict types and focused Ruff pass. These checks establish tool/evidence/source
refusals, bounded fixture waits, topology/endpoint verification, partial-create
cleanup and foreign/replacement refusal; they do not establish actual Kubernetes
eviction behavior. An earlier default-pytest temporary-directory run passed but
reported four stale-directory cleanup warnings; it is retained as an earlier
attempt, not evidence for the corrected directory coordination.

## Actual API proof

The prepared verifier command is:

```sh
uv run python -m scripts.verify_node_maintenance_kind --kind /absolute/path/to/verified/kind --kubectl /absolute/path/to/verified/kubectl --docker /usr/bin/docker --evidence artifacts/node-maintenance/early/evidence.json
```

It creates one control plane and two workers with the pinned Node image, an
explicit private kubeconfig and local Docker socket capture. The early scenarios
are conditional cordon/conflict/uncordon and a managed Deployment blocked by a
PDB, followed by allowance recovery while the reviewed target Pod version stays
unchanged, original-UID absence and replacement scheduling on the other worker.
Actual results, immutable source hashes, failure attempts and verified cleanup
will be recorded after the coordinated run. No actual cluster result is claimed
by this preparation record.

## Completion limits

Expanded multi-node scenarios, public UI/PTY behavior, full production/critical/
changed-line coverage and every required hosted exact-head job remain pending.
The ordinary PR matrix has 27 jobs; release-time manual six-environment
qualification and three repetitions remain separate. Published artifacts remain
0.4.0. This issue does not authorize tags, packages, hosting or DNS changes.
