# Owned Helm chart

This original chart contains only synthetic data. The disposable-cluster verifier
installs it and upgrades it twice as fixture preparation, then exercises KubeRich's
read and reviewed rollback service. Installation and upgrade are not application
features in this change.

The ConfigMap exposes an observable revision effect; the Secret, values and notes
exercise default redaction and deliberate disclosure. Optional rollback hook Jobs
use the shared digest-pinned owned shell image. The verifier tests successful,
failed and time-limited hook execution and removes its entire owned cluster.
