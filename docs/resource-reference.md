# Resource reference

Generated from the standard-resource registry for source version `SOURCE_VERSION`.

Discovery chooses a served API version. Availability still depends on your cluster
and permissions. Pods and namespaces also have dedicated workspace views.

## Standard views

| Resource / aliases | API group | Scope | Columns |
| --- | --- | --- | --- |
| `deployments`, `deploy`, `deployment` | apps | Namespace | namespace, name, ready, desired, updated, available, age |
| `replicasets`, `rs`, `replicaset` | apps | Namespace | namespace, name, desired, current, ready, age |
| `statefulsets`, `sts`, `statefulset` | apps | Namespace | namespace, name, ready, desired, current, updated, age |
| `daemonsets`, `ds`, `daemonset` | apps | Namespace | namespace, name, desired, current, ready, available, age |
| `jobs`, `job` | batch | Namespace | namespace, name, status, succeeded, completions, active, failed, age |
| `cronjobs`, `cj`, `cronjob` | batch | Namespace | namespace, name, schedule, suspend, active, last-schedule, age |
| `services`, `svc`, `service` | core | Namespace | namespace, name, type, cluster-ip, external-ip, ports, age |
| `endpoints`, `ep`, `endpoint` | core | Namespace | namespace, name, ready, not-ready, ports, age |
| `ingresses`, `ing`, `ingress` | networking.k8s.io | Namespace | namespace, name, class, hosts, address, age |
| `configmaps`, `cm`, `configmap` | core | Namespace | namespace, name, data, binary, age |
| `secrets`, `sec`, `secret` | core | Namespace | namespace, name, type, data, age |
| `nodes`, `no`, `node` | core | Cluster | name, status, roles, version, age |
| `persistentvolumeclaims`, `pvc` | core | Namespace | namespace, name, status, volume, capacity, access-modes, storage-class, age |
| `persistentvolumes`, `pv` | core | Cluster | name, capacity, access-modes, reclaim, status, claim, storage-class, age |
| `storageclasses`, `sc`, `storageclass` | storage.k8s.io | Cluster | name, provisioner, reclaim, binding, expansion, age |

See [the workspace explanation](resource-workspace.md) for standard and discovered views.
