# Bench GitOps config

Helm values for a disposable local Kubernetes bench, and the Argo CD
`Application` objects that sync them.

An automated agent opens pull requests against `apps/**/values.yaml` here.
`policy/allowed-paths.yaml` is the allow-list it is held to.

`clusters/bench/terragrunt.hcl` is a stub stack with no cloud behind it (the
`null` provider only). On a pull request touching it,
`.github/workflows/tf-plan.yml` plans it and posts a `tf-plan` check run.

Nothing here is deployed anywhere but a throwaway local cluster.
