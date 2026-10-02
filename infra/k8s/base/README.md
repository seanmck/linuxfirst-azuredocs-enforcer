# Kubernetes deployment

The AKS deployment uses one shared cluster with strict ownership boundaries:

- `infra/k8s/platform` owns the `azuredocs-prod` and `azuredocs-staging`
  namespaces and every shared cluster-scoped object: `PriorityClass`,
  `ClusterIssuer`, and the Karpenter `NodePool`.
- `infra/k8s/base` contains only reusable namespaced workloads and supporting
  resources. Secret access uses a namespace-local `Role` and `RoleBinding`.
- `infra/k8s/overlays/prod` renders into `azuredocs-prod`.
- `infra/k8s/overlays/dev` renders the staging environment into
  `azuredocs-staging`. The `dev` directory name is retained for CI and
  promotion-workflow compatibility.

RabbitMQ, Redis, PVCs, generated secrets, `SecretProviderClass`, database
connection secret, workload identity annotations, and telemetry configuration
are rendered independently in each namespace. Stateful services are not shared
between environments. Each namespace also receives a generous `ResourceQuota`
and `LimitRange`; no default-deny `NetworkPolicy` is applied because the full
set of required external and cluster egress is not enumerated here.

## Argo CD sync order

Sync `infra/argocd/apps/platform-app.yaml` before the workload Applications.
Its sync wave is `-1`; production and staging use wave `0`. The platform
Application must become healthy before either workload Application is allowed
to create namespaced resources. The `linuxfirst-docs-platform` AppProject
permits only the platform Application's required cluster-scoped resource kinds
and grants no namespaced resources. The `linuxfirst-docs` AppProject permits
only namespaced workload resources in `azuredocs-prod` and
`azuredocs-staging`, with no cluster-scoped permissions.

## Migration to the shared cluster

1. Install the required CRDs/controllers (cert-manager, KEDA, Secrets Store CSI,
   and Karpenter) before syncing these Applications.
2. Add Azure federated identity credentials for every workload identity and
   service-account subject in both new namespaces before cutover. In
   particular, create credentials for
   `system:serviceaccount:azuredocs-prod:secret-reader`,
   `system:serviceaccount:azuredocs-prod:azuredocs-app-sa`,
   `system:serviceaccount:azuredocs-staging:secret-reader`, and
   `system:serviceaccount:azuredocs-staging:azuredocs-app-sa`, using each
   overlay's configured managed identity client ID.
3. Sync the platform Application and verify both namespaces and shared
   cluster-scoped resources are healthy.
4. Sync staging, verify `https://dev.linuxdocs.seanmck.dev`, OAuth callback,
   Key Vault secret projection, database access, queues, telemetry, and PVC
   binding. After the renamed `linuxfirst-docs-staging` Application is healthy,
   delete the legacy `linuxfirst-docs-dev` Application so it cannot continue
   reconciling the old destination.
5. Sync production and verify `https://linuxdocs.seanmck.dev` before moving
   traffic or removing resources from the previous cluster/namespace.

Render locally with:

```bash
kubectl kustomize infra/k8s/platform
kubectl kustomize infra/k8s/overlays/dev
kubectl kustomize infra/k8s/overlays/prod
```
