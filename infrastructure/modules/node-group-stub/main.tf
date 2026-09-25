# A node-group module with no cloud behind it (#67).
#
# The bench has no AWS account, so the `tf-plan` workflow plans this
# instead of a real EKS node group. It keeps the one distinction the gate
# cares about, because the real resources have it too:
#
#   - a size change (desired/min/max) is an in-place UPDATE, as it is on
#     aws_eks_node_group.scaling_config;
#   - an instance-type change is a REPLACE, as it is on a launch template
#     or a node group whose instance_types changed.
#
# Only `hashicorp/null` and the built-in `terraform_data` are used. The
# workflow refuses to apply the base state for anything else
# (tools/tf_plan_summary.py --assert-stub).

terraform {
  required_version = ">= 1.5"
  required_providers {
    null = {
      source  = "hashicorp/null"
      version = "~> 3.2"
    }
  }
}

variable "cluster_name" {
  type = string
}

variable "node_groups" {
  type = map(object({
    instance_type = string
    desired_size  = number
    min_size      = number
    max_size      = number
  }))
}

# Scaling: updated in place.
resource "terraform_data" "scaling" {
  for_each = var.node_groups
  input = {
    cluster      = var.cluster_name
    desired_size = each.value.desired_size
    min_size     = each.value.min_size
    max_size     = each.value.max_size
  }
}

# The launch template: a new instance type replaces it.
resource "null_resource" "launch_template" {
  for_each = var.node_groups
  triggers = {
    cluster       = var.cluster_name
    instance_type = each.value.instance_type
  }
}

output "node_groups" {
  value = { for name, ng in var.node_groups : name => ng.desired_size }
}
