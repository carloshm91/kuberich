# KubeRich Homebrew tap

This is the prepared tap scaffold. KubeRich's release tooling generates
`Formula/kuberich.rb` from the published immutable sdist and its audited locked
runtime resources. The formula installs dependencies into a private virtual
environment and tests actual CLI behavior and required UI assets.

The public tap has not been created. After explicit publication approval, the
maintainer confirms control of organization `kuberich` and initializes
`kuberich/homebrew-tap` from this scaffold. The intended public command is
`brew install kuberich/tap/kuberich`; the namespace is not reserved or activated
by this scaffold. The source stays `carloshm91/kuberich`. Release
automation opens an update PR; passing Linux/macOS checks and maintainer review
are required before merging. It never replaces a published version or merges
its own PR. Candidate formulas with local file URLs are for owned tests only.

See the source repository's `docs/homebrew.md` for preparation and qualification.
