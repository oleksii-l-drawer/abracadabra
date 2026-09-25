# The bench cluster's node groups (#63, #67). A stub: it plans against
# infrastructure/modules/node-group-stub, which has no cloud behind it.
#
# `inputs` holds literals only - #63's editor changes a number here and
# refuses anything that is an expression. `clusters/*/terragrunt.hcl` is
# `hitl` in policy/allowed-paths.yaml: a PR touching it always asks a human,
# and the `tf-plan` check is evidence for that human, never a merge.

terraform {
  source = "../../infrastructure/modules/node-group-stub"
}

# Local state only. The workflow points TF_PLAN_STATE_DIR at a scratch dir,
# builds the base branch's state there, then plans the PR head against it,
# so the plan shows the PR's diff rather than "create everything". A real
# stack reads remote state under a plan-only role instead (#67, not built).
generate "backend" {
  path      = "backend.tf"
  if_exists = "overwrite"
  contents  = <<-EOF
    terraform {
      backend "local" {
        path = "${get_env("TF_PLAN_STATE_DIR", get_terragrunt_dir())}/terraform.tfstate"
      }
    }
  EOF
}

inputs = {
  cluster_name = "bench"
  node_groups = {
    workers = {
      instance_type = "m6i.large"
      desired_size  = 2
      min_size      = 1
      max_size      = 4
    }
  }
}
