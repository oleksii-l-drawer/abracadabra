# Bench GitOps config

Helm values for a disposable local Kubernetes bench, and the Argo CD
`Application` objects that sync them.

An automated agent opens pull requests against `apps/**/values.yaml` here.
`policy/allowed-paths.yaml` is the allow-list it is held to.

Nothing here is deployed anywhere but a throwaway local cluster.
