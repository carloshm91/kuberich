# KubeRich Homebrew tap scaffold

This is the prepared tap scaffold. KubeRich's release tooling generates
`Formula/kuberich.rb` from the published immutable sdist and its audited locked
runtime resources. The formula installs dependencies into a private virtual
environment and tests actual CLI behavior and required UI assets.

The public tap is [kuberich/homebrew-tap](https://github.com/kuberich/homebrew-tap),
and its installation command is `brew install kuberich/tap/kuberich`.
This directory prepares reviewed tap changes; editing it does not update the
public tap or publish a new version. The application source remains
`carloshm91/kuberich`. Release
automation opens an update PR; passing Linux/macOS checks and maintainer review
are required before merging. It never replaces a published version or merges
its own PR. Candidate formulas with local file URLs are for owned tests only.

The workflow grants trust to this formula only, then requires style, strict
online audit, source installation, installed behavior and removal. See the
source repository's `docs/homebrew.md` for preparation and qualification.
