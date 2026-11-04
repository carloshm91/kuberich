# KubeRich Homebrew tap

This is the scaffold for the public [project tap](https://github.com/kuberich/homebrew-tap). KubeRich's release tooling generates
`Formula/kuberich.rb` from the published immutable sdist and its audited locked
runtime resources. The formula installs dependencies into a private virtual
environment and tests actual CLI behavior and required UI assets.

Install the activated tap version with `brew install kuberich/tap/kuberich`.
Organization `kuberich` owns the separate `kuberich/homebrew-tap` repository;
the application source stays `carloshm91/kuberich`. Editing this scaffold does
not publish a formula or change the existing tap. Release
automation opens an update PR; passing Linux/macOS checks and maintainer review
are required before merging. It never replaces a published version or merges
its own PR. Candidate formulas with local file URLs are for owned tests only.

See the source repository's `docs/homebrew.md` for preparation and qualification.
