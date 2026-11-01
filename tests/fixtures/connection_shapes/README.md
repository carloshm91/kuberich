# Synthetic kubeconfig shapes

These templates contain invented contexts, reserved `.invalid` endpoints and
synthetic tokens. No client, account, cluster, key or usable credential is copied
from a developer's configuration. Tests replace marked TLS values with freshly
generated certificates in their owned directory and replace provider endpoints
with an owned loopback API. Provider executables are harmless owned stand-ins.

The cases cover EKS and AKS exec arguments, GKE ExecCredential, Rancher URL
prefixes, OpenShift bearer credentials, k3s relative certificate files, kind
inline certificates, Teleport exec certificates/SNI/opaque extensions and
Tailscale's documented unused-token entry. They verify local shape and transport
contracts; they do not certify real cloud exchange, browser login, tenant policy,
Teleport routing or a live tailnet.

Primary shape references:

- [AWS kubeconfig setup](https://docs.aws.amazon.com/eks/latest/userguide/create-kubeconfig.html)
- [Azure kubelogin](https://azure.github.io/kubelogin/concepts/exec-plugin.html)
- [GKE authentication](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/cluster-access-for-kubectl)
- [Rancher access](https://ranchermanager.docs.rancher.com/how-to-guides/new-user-guides/manage-clusters/access-clusters/)
- [OpenShift CLI access](https://docs.redhat.com/en/documentation/openshift_container_platform/4.20/html/cli_tools/openshift-cli-oc)
- [k3s access](https://docs.k3s.io/cluster-access)
- [kind quick start](https://kind.sigs.k8s.io/docs/user/quick-start/)
- [Teleport kubeconfig contract](https://github.com/gravitational/teleport/blob/master/lib/kube/kubeconfig/kubeconfig.go)
- [Tailscale configuration shape](https://github.com/tailscale/tailscale/blob/main/cmd/tailscale/cli/configure-kube.go)
