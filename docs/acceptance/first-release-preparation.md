# First 0.1.0 preparation: #150

The source/lock version is `0.1.0`; authored notes cover features, fixes,
compatibility/migrations, installation, upgrades/uninstall and known limits.
This prepares a candidate, without a tag, package upload, public tap, final-site
deployment or DNS change. The completed development qualifier is
[D06 #51](workload-checkpoint.md); exact candidate qualification remains separate.

## Measured local preparation

The new installation guide distinguishes a trusted local wheel, conditional
public Python/Homebrew channels and four standalone archives. Source scope is
Ubuntu 24.04 x86_64/macOS 26 ARM on Python 3.12–3.14; native archives and Homebrew
have their separate measured hosts/floors. Provider/physical-terminal and macOS
14 Intel limits remain explicit. Both websites reuse the maintained guides.

The actual application generated new workspace and owned-kind CoreDNS SVGs
with installed metadata `0.1.0`. The producer used synthetic loopback resources
and an explicitly owned disposable cluster; cluster deletion and caller isolation
passed. Original commands/logs and media remain under `artifacts/launch150`.
The tracked media inventory retains application tree/version and image digests.
No screenshot text/version was hand-edited.

Local checks passed:

- 126 initial site/native-parser/UI cases in 134.17 seconds.
- 307 release-notes, phase-policy and Homebrew checks in 14.41 seconds.
- Two real uv/pipx upgrade trials in 58.32 seconds, from immutable owned
  `0.1.0rc1` into the real `0.1.0` wheel. Normal upgrade, actual upgraded
  navigation/shell, preference/caller preservation and uninstall passed. This is
  an unpublished source baseline, not a fabricated earlier public release.
- Seventeen site behavior/negative-control cases with the final captured media
  in 28.19 seconds. Changing a source version does not imply package availability.
- Ruff/format over 532 files, strict types over 146 application/gate/site files,
  whitespace and plan validation; locked Node QA audit reported zero vulnerabilities.

The two-surface static build passed **53 pages, 1,988 local links/assets and
68 files**. Real Chrome 143.0.7499.169 with locked Playwright 1.64.0/axe 4.14.0
checked every page at desktop/mobile widths, 320px overflow, keyboard skip/menu,
clipboard success/denial and navigation with JavaScript disabled. There were
zero automated A/AA violations, browser failures or external runtime requests.
The retained desktop/mobile images were visually reviewed. Automated checks do
not establish physical screen-reader/terminal/font/clipboard certification.

Site manifest SHA-256: `5ff40620cd06e8dfef7651d9aa27973bf11d712e58e02197f3b38ed62bdf44b8`.
Browser report SHA-256: `27c4542e55245536d17ac5c2281b672e86e0720cb11c4146798e4d1bd949ea2e`.
These are local preparation bytes. The protected candidate/main run and original
audited distribution/native/installation artifacts need their own retained IDs
and independent reading before this issue closes. Local checks do not substitute
for the six-source/four-native release matrix or three consecutive owned rounds.

## Publication handoff

The existing [hosting procedure](../website.md#final-product-hosting-cloudflare-pages)
proposes the two Direct Upload projects, `kuberich.com`, `docs.kuberich.com` and
an explicit `www` redirect, with HTTPS, immutable manifest/deployment association
and rollback. The approved development provider hosts retain their earlier
published bytes; source preparation does not redeploy them.

#89 still owns concrete publication approval, actual PyPI/TestPyPI publisher
ownership, the public `kuberich/homebrew-tap` and limited update credential,
public installed-channel verification, final website/custom-domain activation
and verified redirects. The GitHub organization already exists, while a namespace
lookup alone does not prove package ownership or activate a channel. Publication
and owner environment review remain required after the concrete candidate is ready.
