---
name: python-textual-kubernetes
description: Build, review, and test Python Textual terminal applications that interact with Kubernetes, including live resource views, logs, interactive exec, and plugins. Use for terminal client engineering and its relevant security boundaries; not for web UI design or unrelated cluster administration.
---

# Python, Textual, and Kubernetes

Read repository guidance and the current issue first. Preserve its framework,
client, supported platforms, coverage policy, and authorized scope. Consult
current official Textual and Kubernetes/client documentation when depending on
version-specific behavior.

## State and concurrency

- Separate transport adapters, domain state, application operations, and widgets.
  Generated SDK objects should not become the UI's public contract.
- Use an explicit client per context, with a captured session generation. Cancel
  and await old work when scopes change; reject late responses from old sessions.
- Implement list/watch continuity, pagination, 410 relisting, EOF/reconnect,
  bounded backoff, and meaningful permission errors. Resource versions are opaque.
- Own every task, stream, client session, subprocess, and port-forward. Test exit
  and cancellation as carefully as the successful path. Threads need cooperative
  cancellation; cancelling an await does not kill a blocking worker thread.
- Batch UI updates and preserve selection by resource identity. Bound log
  storage and queues, distinguish pause from follow, and sort typed values.

## Terminal experience

- Use Textual's message/worker APIs without synchronous I/O in ordinary handlers.
  Marshal updates from threads correctly; do not mutate widgets from worker threads.
- Test focus, hints, navigation history, escape behavior, small windows, Unicode
  width, horizontal scrolling, and updates while filtering or selecting rows.
- Full-terminal exec/editor handoff uses App.suspend and the real terminal.
  Embedded interactive terminals require additional emulation and lifecycle work;
  a log widget is not a terminal emulator. Textual Web cannot use app suspension.
- Pass subprocess argument vectors and explicit target context/namespace/container.
  Capture targets before awaiting. Verify terminal restoration after exit,
  interruption, resize, failure, and repeated sessions using PTY tests.

## Kubernetes and local trust boundaries

- Never use the developer's default cluster for integration tests. Use disposable
  contexts and refuse unsafe fallback when fixture setup fails.
- Treat names, annotations, logs, kubeconfig fields, and plugin output as untrusted
  display/process inputs. Escape markup and terminal control sequences; avoid
  raw shell interpolation and leaking credentials in errors or support bundles.
- Put read-only guards, target confirmation, permission/conflict handling, and
  uncertain mutation outcomes in testable services. Do not blindly retry writes.
- Treat plugins as explicitly invoked local code with user privileges. Preserve
  documented scopes/environment semantics and clean up processes on cancellation.
- Distinguish unavailable metrics from zero and permission denial from no data.

## Evidence

Use pure tests for decisions, a controllable fake API for transport edge cases,
Textual Pilot for UI behavior, kind for real API contracts, and PTYs for terminal
handoff. Measure the full production package, including unimported modules;
honor the repository's separate line/branch thresholds. Do not optimize coverage
by hiding integrations. Test built artifacts in clean environments.

When reviewing, report concrete failure scenarios and source locations. When
implementing, verify the selected issue and avoid broad unrelated rewrites.

Sources: [Textual](https://textual.textualize.io/guide/),
[Kubernetes API concepts](https://kubernetes.io/docs/reference/using-api/api-concepts/),
[kubernetes_asyncio](https://github.com/tomplus/kubernetes_asyncio).
