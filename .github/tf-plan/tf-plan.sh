#!/usr/bin/env bash
# Plan every Terragrunt stack for a PR and write one summary (#67).
#
# usage: tf-plan.sh <base-sha> <out-dir>     (run from the repo root, PR head checked out)
#
# Writes <out-dir>/<stack>.head.json (the plans the check is counted from)
# and <out-dir>/summary.json (tools/tf_plan_summary.py's counts across
# every stack). Exits non-zero on anything it cannot plan; the workflow then
# posts a `failure` check, which the agent reads as "unavailable" -> HITL.
#
# Every `clusters/*/terragrunt.hcl` is planned, not only the changed ones: a
# module change reaches every stack that uses it, and planning one stub
# stack costs seconds.
#
# The base state. The stub has local state only, so to show the PR's diff
# (an update, a replace) rather than "create everything", the base commit's
# plan is applied into a scratch state dir first, then the head is planned
# against it. That apply is refused unless the plan uses only the null
# provider and the built-in terraform_data (--assert-stub). A real stack does
# not do this: it reads remote state under a plan-only role.
set -euo pipefail

base_sha="${1:?usage: tf-plan.sh <base-sha> <out-dir>}"
out="${2:?usage: tf-plan.sh <base-sha> <out-dir>}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(pwd)"
summarise=(python3 "${here}/tf_plan_summary.py")

# terragrunt wraps terraform's stdout in log lines unless told not to, and
# `show -json` has to be the bare document.
export TG_TF_FORWARD_STDOUT=true TG_NON_INTERACTIVE=true TF_IN_AUTOMATION=1 TF_INPUT=0

mkdir -p "${out}"
rm -rf "${out}/base"
git worktree add --quiet --detach "${out}/base" "${base_sha}"
trap 'git -C "${root}" worktree remove --force "${out}/base" >/dev/null 2>&1 || true' EXIT

stacks() {
  (cd "$1" && for f in clusters/*/terragrunt.hcl; do [[ -f "${f}" ]] && dirname "${f}"; done) || true
}
mapfile -t head_stacks < <(stacks "${root}")
mapfile -t base_stacks < <(stacks "${out}/base")

# A stack the PR deletes would be a destroy this job cannot plan (its code is
# gone from the head). Fail rather than report a plan without it.
for stack in "${base_stacks[@]}"; do
  [[ -f "${root}/${stack}/terragrunt.hcl" ]] || {
    echo "the PR removes ${stack}; its destroy cannot be planned here" >&2
    exit 1
  }
done
(( ${#head_stacks[@]} )) || { echo "no clusters/*/terragrunt.hcl to plan" >&2; exit 1; }

plans=()
for stack in "${head_stacks[@]}"; do
  name="$(basename "${stack}")"
  export TF_PLAN_STATE_DIR="${out}/state/${name}"
  rm -rf "${TF_PLAN_STATE_DIR}"
  mkdir -p "${TF_PLAN_STATE_DIR}"

  if [[ -f "${out}/base/${stack}/terragrunt.hcl" ]]; then
    echo "::group::${stack}: base state (${base_sha:0:7})"
    (
      cd "${out}/base/${stack}"
      terragrunt plan -out=base.tfplan -lock=false
      terragrunt show -json base.tfplan > "${out}/${name}.base.json"
    )
    "${summarise[@]}" --assert-stub "${out}/${name}.base.json"
    (cd "${out}/base/${stack}" && terragrunt apply -lock=false base.tfplan)
    echo "::endgroup::"
  fi

  echo "::group::${stack}: plan"
  (
    cd "${root}/${stack}"
    terragrunt plan -out=head.tfplan -lock=false
    terragrunt show -json head.tfplan > "${out}/${name}.head.json"
  )
  echo "::endgroup::"
  plans+=("${out}/${name}.head.json")
done

"${summarise[@]}" "${plans[@]}" > "${out}/summary.json"
cat "${out}/summary.json"
