# Kubetrol Homebrew tap

This is the prepared tap scaffold. Kubetrol's release tooling generates
`Formula/kubetrol.rb` from the published immutable sdist and its audited locked
runtime resources. The formula installs dependencies into a private virtual
environment and tests actual CLI behavior and required UI assets.

The public tap has not been created. After explicit publication approval, the
maintainer initializes `carloshm91/homebrew-tap` from this scaffold. Release
automation opens an update PR; passing Linux/macOS checks and maintainer review
are required before merging. It never replaces a published version or merges
its own PR. Candidate formulas with local file URLs are for owned tests only.

See the source repository's `docs/homebrew.md` for preparation and qualification.
