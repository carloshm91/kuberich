# Security policy

No application release is currently supported because none has been published.
After releases begin, security fixes target the latest released minor line.
The support matrix will identify its exact supported patch version.

Report suspected vulnerabilities privately to **carloshm91@gmail.com**. Include
the version, affected behavior, and a minimal sanitized reproduction. Do not
post credentials, kubeconfigs, cluster endpoints, or exploit details publicly
before coordinated disclosure. Maintainer response times are best effort.

Kubetrol uses the current user's Kubernetes credentials and permissions. It is
not a separate security boundary around the cluster. It will verify TLS by
default, represent permission failures explicitly, and identify the target
context/namespace/resource before modifying operations.

Plugins are user-installed local commands with the user's privileges. They are
not sandboxed. Plugin execution must be deliberate; opening a repository or
browsing a cluster must not automatically run a plugin found there.

The implementation must treat resource fields, logs, kubeconfig values, plugin
output, and downloaded update metadata as untrusted input. Secret redaction,
terminal-control handling, argument-vector execution, dependency auditing, and
release provenance are tracked in the backlog.

Tests use disposable local clusters. No test may silently select or modify a
developer's default production context.
