# Helm parser fixture provenance

`upstream/` contains unchanged Helm CLI golden output files from the official
[Helm project](https://github.com/helm/helm), licensed under
[Apache-2.0](https://github.com/helm/helm/blob/v4.3.1/LICENSE). These are upstream
unit-test shapes, not output executed by KubeRich or evidence of cluster support.

- v3.22.1 source: `cmd/helm/testdata/output/` at
  `d6c1a0e4027caa6abc7892e7ea9f0cda7447baa3`.
- v4.3.1 source: `pkg/cmd/testdata/output/` at
  `c0d08d0d6d9424d4a14febb5e8a3e51b0dd00dff`.
- Both upstream status fixtures intentionally omit a revision `version` and
  cannot establish release identity. Production parsers reject them unchanged.
- v3 does not have an equivalent complete `list-json.txt` golden fixture.

`synthetic/` contains original KubeRich examples written for #66. They are
explicitly synthetic source-shape cases and contain no real release information.
They must not be described as executed CLI output.

SHA-256 checksums are recorded in `checksums.json`; tests check exact bytes.
Actual owned-cluster captures, when available, have separate execution evidence.
