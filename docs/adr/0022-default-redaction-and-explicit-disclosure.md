# Redact ordinary views and require deliberate value disclosure

Status: Accepted for the source snapshot described here.
Migrated: 2026-11-01.

## Context

Kubernetes fields and external output are untrusted display data, while ConfigMaps, Secrets, and
editor drafts can contain genuinely sensitive values.

## Decision

- Escape terminal controls and Rich markup independently of credential redaction. Keep raw
  helper output, manifests, tokens, and exception locals out of ordinary diagnostics.
- Require a fresh target/version check for deliberate key reveal or copy and explicit local-
  disclosure consent before an editor sees a full manifest. Disable application screenshot
  export for the data view.

## Consequences

- Redaction is pattern-based and cannot recognize arbitrary confidential prose. Explicit
  copy/editor access can disclose real values to local programs.
- Read permission, application read-only policy, display escaping, and confidentiality are
  separate boundaries. Base64 does not encrypt a secret.

Clipboard backends only write; production does not read the clipboard to prove
receipt. Local native copy uses a dedicated process-purpose/input boundary where
needed, while OSC52 sends size-limited base64 frames through the trusted terminal.
Headless copies stay in application memory. Sensitive bytes do not become argv,
executable code, diagnostics, or unsolicited remote clipboard requests.

## Source and related decisions

This record extracts an implemented decision from the [previous architecture
log](../internal/architecture-history/README.md). It does not requalify its historical
measurements.

- [src/kuberich/security/presentation.py](../../src/kuberich/security/presentation.py)
- [src/kuberich/security/controls.py](../../src/kuberich/security/controls.py)
- [src/kuberich/diagnostics/redaction.py](../../src/kuberich/diagnostics/redaction.py)
- [src/kuberich/services/configuration_data.py](../../src/kuberich/services/configuration_data.py)
- [src/kuberich/ui/configuration_data.py](../../src/kuberich/ui/configuration_data.py)
- [src/kuberich/domain/clipboard.py](../../src/kuberich/domain/clipboard.py)
- [src/kuberich/services/clipboard.py](../../src/kuberich/services/clipboard.py)

Related: [0004](0004-credential-helpers-and-delegation.md), [0013](0013-reviewed-conditional-writes.md).
