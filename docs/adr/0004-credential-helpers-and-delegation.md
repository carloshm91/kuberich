# Preserve the configured credential identity when delegating tools

Status: Accepted for the source snapshot described here.
Migrated: 2026-11-01.

## Context

An SDK read and a later kubectl process must use the same endpoint, credentials, TLS, proxy, and
impersonation choices even if the source environment changes.

## Decision

- Treat kubeconfig and its exec helpers as trusted local configuration. Preserve helper argv,
  environment, originating directory, and declared interaction mode.
- Cache and refresh credentials per session. Prepare a private single-context connection for
  delegated tools instead of asking them to reload the ambient current context.

## Consequences

- Authentication helpers may run for ordinary reads, including application read-only mode;
  operator plugins require a separate explicit invocation.
- Tokens and certificate material stay out of command diagnostics. Client-go helper
  compatibility and real cloud-provider policy remain separate verification questions.

The session adapter configures its HTTP pool explicitly rather than using SDK
default loaders. Proxy and TLS-name handling must remain consistent through that
boundary; automatic netrc identity stays disabled. The pinned SOCKS connector
needs an SSLContext hostname adaptation because it drops request-level overrides.
That local compatibility mechanism is separate from real-provider certification.

## Source and related decisions

This record extracts an implemented decision from the [previous architecture
log](../internal/architecture-history/README.md). It does not requalify its historical
measurements.

- [src/kuberich/adapters/credentials.py](../../src/kuberich/adapters/credentials.py)
- [src/kuberich/adapters/credential_child.py](../../src/kuberich/adapters/credential_child.py)
- [src/kuberich/adapters/kubernetes.py](../../src/kuberich/adapters/kubernetes.py)
- [src/kuberich/domain/connection_overrides.py](../../src/kuberich/domain/connection_overrides.py)

Related: [0003](0003-explicit-context-sessions.md), [0008](0008-external-process-ownership.md).
