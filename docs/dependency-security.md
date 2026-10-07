# Dependency security and release composition

Q04 #35 adds an executable gate over the installed runtime, separate from the
development environment. Run the following from the checkout:

```sh
uv sync --locked --group dev
uv build
uv run python -m scripts.check_supply_chain
uv run python -m scripts.check_supply_chain --verify
```

The first command pair builds local candidates; it publishes nothing. Generation
owns two temporary installations of the exact built wheel. The locked installation
uses the runtime-only uv export and verified download hashes; the fresh installation
resolves the wheel's declared requirements. Both check installed dependency closure,
`uv pip check` and the installed CLI version. The inventory reads distribution
metadata without importing the Kubernetes SDK or executing authentication helpers.

Each installation receives a strict pip-audit check over every exact dependency,
a schema-validated CycloneDX 1.6 JSON SBOM and the original dependency notices.
The gate compares the SBOM's names/versions against the installed closure. It binds
both the wheel and source archive SHA-256, the lock and reviewed policy to the
reports in `artifacts/security/provenance.json`. Verification rejects changed
artifacts, incomplete/skipped audits, missing notices, mismatched SBOM composition,
unapproved licenses and floating external Actions. Audit evidence expires after
24 hours; refresh it before release qualification. Advisory-service or scanner
failures fail the gate instead of producing a clean bill of health.

These are measured, unsigned candidate sidecars. They are not an OIDC attestation,
an assertion that dependencies cannot contain unknown vulnerabilities, or a lock
on dependencies chosen by every future installation. D02 #36 owns publication and
attestation; standalone dependency redistribution remains D05 #49.

## Exceptions and license review

`scripts/supply_chain_policy.json` is reviewed with the code. There are currently
no vulnerability exceptions. Every reported vulnerability blocks unless a single
matching exception specifies its normalized package, exact version, CVE/GHSA/PYSEC,
Kubetrol issue, accountable GitHub owner, mitigation rationale and an expiry within
90 days. Missing fields, wildcard versions, blanket ignores, expired exceptions
and ambiguous alias matches are rejected. Production exceptions require review
in their tracked issue and PR; passing a synthetic waiver test grants no waiver.

SPDX license expressions are allowlisted. Legacy metadata for aiosignal, multidict
and python-dateutil has version-specific reviewed mappings backed by the original
license files. Unknown licenses or changed legacy metadata require a new review.
python-dateutil's original notice states that its BSD license covers all its code;
the generated notices preserve both license sections.

Pyte 0.8.2 remains an unmodified, dynamically imported LGPL-3.0-only dependency.
Kubetrol's own code remains MIT. Preserve Pyte's original license, authors and
corresponding source when bundling a standalone distribution, and preserve users'
ability to replace the library as required by its license. The candidate manifest
records the pinned Pyte source archive URL and SHA-256 from uv.lock. wcwidth and
every transitive dependency receive their own notices. The wheel/sdist do not
vendor these separately installed libraries; release sidecars record their actual
composition. A future bundler must qualify its concrete redistribution method.

## Runtime security boundaries

The full deterministic inventory remains the 29 modules listed under
`tool.kubetrol.coverage.critical_modules`. Each must independently reach 100% lines
and branches; gate scripts and their negative controls are development code and
do not inflate application coverage. See [quality](quality.md),
[security primitives](security-primitives.md) and [the threat model](kubetrol-threat-model.md).

Actual child-process tests demonstrate that selected values containing shell
substitutions, quotes, semicolons and option-looking text remain literal argv.
Rich rendering tests cover markup/OSC/C0/C1/bidi controls and redaction. Exclusive
log-export tests reject existing files, hardlinks, dangling symlinks, directories
and a competing writer without overwriting them, and verify temporary-file cleanup.
The shared process boundary supports these tests; ordinary plugin registration,
template semantics and operator invocation remain U03 #58. Resource exports beyond
the implemented log viewer remain O06 #73.

## Sources

- [pip-audit usage and security model](https://github.com/pypa/pip-audit)
- [CycloneDX environment inventory](https://cyclonedx-bom-tool.readthedocs.io/en/latest/usage.html)
- [CycloneDX 1.6 schema](https://github.com/CycloneDX/specification/blob/master/schema/bom-1.6.schema.json)
- [Requests negative-control advisory](https://github.com/advisories/GHSA-x84v-xcm2-53pg)

Measured candidate results: [Q04 acceptance](acceptance/dependency-security.md).
