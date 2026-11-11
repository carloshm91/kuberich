# Resource reference

Generated from the standard-resource registry for source version `SOURCE_VERSION`.

Discovery chooses a served API version. Availability still depends on your cluster
and permissions. Pods and namespaces also have dedicated workspace views.

## Standard views

| Resource / aliases | API group | Scope | Columns |
| --- | --- | --- | --- |
| `deployments`, `deploy`, `deployment` | apps | Namespace | namespace, name, ready, desired, updated, available, cpu, memory, cpu-req, cpu-lim, memory-req, memory-lim, cpu-percent-request, cpu-percent-limit, memory-percent-request, memory-percent-limit, metrics, sample, window, extended, age |
| `replicasets`, `rs`, `replicaset` | apps | Namespace | namespace, name, desired, current, ready, cpu, memory, cpu-req, cpu-lim, memory-req, memory-lim, cpu-percent-request, cpu-percent-limit, memory-percent-request, memory-percent-limit, metrics, sample, window, extended, age |
| `statefulsets`, `sts`, `statefulset` | apps | Namespace | namespace, name, ready, desired, current, updated, cpu, memory, cpu-req, cpu-lim, memory-req, memory-lim, cpu-percent-request, cpu-percent-limit, memory-percent-request, memory-percent-limit, metrics, sample, window, extended, age |
| `daemonsets`, `ds`, `daemonset` | apps | Namespace | namespace, name, desired, current, ready, available, cpu, memory, cpu-req, cpu-lim, memory-req, memory-lim, cpu-percent-request, cpu-percent-limit, memory-percent-request, memory-percent-limit, metrics, sample, window, extended, age |
| `jobs`, `job` | batch | Namespace | namespace, name, status, succeeded, completions, active, failed, cpu, memory, cpu-req, cpu-lim, memory-req, memory-lim, cpu-percent-request, cpu-percent-limit, memory-percent-request, memory-percent-limit, metrics, sample, window, extended, age |
| `cronjobs`, `cj`, `cronjob` | batch | Namespace | namespace, name, schedule, suspend, active, last-schedule, cpu, memory, cpu-req, cpu-lim, memory-req, memory-lim, cpu-percent-request, cpu-percent-limit, memory-percent-request, memory-percent-limit, metrics, sample, window, extended, age |
| `services`, `svc`, `service` | core | Namespace | namespace, name, type, cluster-ip, external-ip, ports, age |
| `endpoints`, `ep`, `endpoint` | core | Namespace | namespace, name, ready, not-ready, ports, age |
| `ingresses`, `ing`, `ingress` | networking.k8s.io | Namespace | namespace, name, class, hosts, address, age |
| `configmaps`, `cm`, `configmap` | core | Namespace | namespace, name, data, binary, age |
| `secrets`, `sec`, `secret` | core | Namespace | namespace, name, type, data, age |
| `nodes`, `no`, `node` | core | Cluster | name, status, roles, version, cpu, memory, cpu-req, cpu-lim, memory-req, memory-lim, cpu-percent-request, cpu-percent-limit, memory-percent-request, memory-percent-limit, metrics, sample, window, extended, cpu-capacity, cpu-allocatable, memory-capacity, memory-allocatable, cpu-percent-allocatable, memory-percent-allocatable, age |
| `persistentvolumeclaims`, `pvc` | core | Namespace | namespace, name, status, volume, capacity, access-modes, storage-class, age |
| `persistentvolumes`, `pv` | core | Cluster | name, capacity, access-modes, reclaim, status, claim, storage-class, age |
| `storageclasses`, `sc`, `storageclass` | storage.k8s.io | Cluster | name, provisioner, reclaim, binding, expansion, age |
| `horizontalpodautoscalers`, `hpa` | autoscaling | Namespace | namespace, name, target, min, max, current, desired, metrics, conditions, info, age |
| `verticalpodautoscalers`, `vpa` | autoscaling.k8s.io | Namespace | namespace, name, target, mode, recommended-containers, conditions, info, age |
| `poddisruptionbudgets`, `pdb` | policy | Namespace | namespace, name, min-available, max-unavailable, allowed, current-healthy, desired-healthy, expected-pods, status, info, age |
| `priorityclasses`, `pc` | scheduling.k8s.io | Cluster | name, priority, global-default, preemption, info, age |
| `runtimeclasses`, `runtimeclass` | node.k8s.io | Cluster | name, handler, overhead-cpu, overhead-memory, node-selector, tolerations, info, age |
| `leases`, `lease` | coordination.k8s.io | Namespace | namespace, name, holder, duration-seconds, renew-time, transitions, info, age |
| `networkpolicies`, `networkpolicy`, `netpol` | networking.k8s.io | Namespace | namespace, name, selector, policy-types, ingress-rules, egress-rules, info, age |
| `endpointslices`, `endpointslice` | discovery.k8s.io | Namespace | namespace, name, address-type, service, endpoints, ready, not-ready, unspecified, ports, info, age |
| `ingressclasses`, `ingressclass` | networking.k8s.io | Cluster | name, controller, default, parameters-kind, parameters-scope, info, age |
| `resourcequotas`, `resourcequota`, `quota` | core | Namespace | namespace, name, resources, usage, scopes, exceeded, info, age |
| `limitranges`, `limitrange`, `limits` | core | Namespace | namespace, name, types, items, defaults, constraints, info, age |
| `mutatingwebhookconfigurations`, `mutatingwebhookconfiguration` | admissionregistration.k8s.io | Cluster | name, webhooks, review-versions, failure-policies, side-effects, clients, timeout-min, timeout-max, info, age |
| `validatingwebhookconfigurations`, `validatingwebhookconfiguration` | admissionregistration.k8s.io | Cluster | name, webhooks, review-versions, failure-policies, side-effects, clients, timeout-min, timeout-max, info, age |
| `serviceaccounts`, `sa` | core | Namespace | namespace, name, automount, secrets, image-pull-secrets, info, age |
| `roles`, `role` | rbac.authorization.k8s.io | Namespace | namespace, name, rules, resource-rules, nonresource-rules, aggregation-selectors, info, age |
| `clusterroles`, `clusterrole` | rbac.authorization.k8s.io | Cluster | name, rules, resource-rules, nonresource-rules, aggregation-selectors, info, age |
| `rolebindings`, `rb` | rbac.authorization.k8s.io | Namespace | namespace, name, role-kind, role, service-accounts, users, groups, info, age |
| `clusterrolebindings`, `crb` | rbac.authorization.k8s.io | Cluster | name, role-kind, role, service-accounts, users, groups, info, age |
| `validatingadmissionpolicies`, `validatingadmissionpolicy`, `vap` | admissionregistration.k8s.io | Cluster | name, match-rules, match-conditions, failure-policy, param-kind, validations, observation, info, age |
| `validatingadmissionpolicybindings`, `validatingadmissionpolicybinding`, `vapb` | admissionregistration.k8s.io | Cluster | name, policy, actions, parameters, match-rules, info, age |
| `mutatingadmissionpolicies`, `mutatingadmissionpolicy`, `map` | admissionregistration.k8s.io | Cluster | name, match-rules, match-conditions, failure-policy, param-kind, mutations, reinvocation, info, age |
| `mutatingadmissionpolicybindings`, `mutatingadmissionpolicybinding`, `mapb` | admissionregistration.k8s.io | Cluster | name, policy, parameters, match-rules, info, age |

## Events

The dedicated `:events` view uses its discovered Event API. Its columns are:
`namespace`, `type`, `reason`, `object`, `occurrences`, `last-seen`, `reporter`.
Raw rows identify individual Events; grouped rows summarize retained observations
by type, reason and object identity. Group rows are not Kubernetes objects.
See [Events and curated views](resource-workspace.md#curated-read-only-views).

See [the workspace explanation](resource-workspace.md) for standard and discovered views.
