"""A Terragrunt plan as evidence for the gate, never as a merge authority (#67).

**Where the plan runs.** Not here. `terragrunt plan` needs provider
credentials - the state bucket and lock table, `ec2:Describe*` at least -
and PRD §11 keeps the agent's only write credential the Git token and its
cloud footprint read-only. So the plan runs in CI on the GitOps repo, under
a plan-only role that repo already owns, and posts a check run named
`tf-plan` on the PR head. The agent reads that check: a read of CI's result,
not a cloud credential.

**The counting is code.** `summarise_plan` turns `terraform show -json` into
counts - add, change, destroy, replace - and the resource types touched. CI
runs the same function (`tools/tf_plan_summary.py`) and puts its JSON in the
check's `output.text`, so what the gate reads was computed by this code, not
narrated by a model (PRD §10 rule 1).

**It can only fail a change.** `plan_clean` is false on any destroy or
replace, and on a plan that is missing, still running, failed or unreadable -
fail closed. A clean plan does not make a change mergeable; it only stops
being a reason to ask.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

CHECK_NAME = "tf-plan"

# `terraform show -json` spells a replacement as both orders of the pair.
_REPLACE = ({"delete", "create"},)


@dataclass(frozen=True)
class PlanSummary:
    add: int = 0
    change: int = 0
    destroy: int = 0
    replace: int = 0
    resource_types: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "add": self.add,
            "change": self.change,
            "destroy": self.destroy,
            "replace": self.replace,
            "resource_types": list(self.resource_types),
        }


def summarise_plan(plan: dict[str, Any]) -> PlanSummary:
    """Counts from a `terraform show -json` document."""
    counts: Counter[str] = Counter()
    types: set[str] = set()
    for rc in plan.get("resource_changes") or []:
        actions = set((rc.get("change") or {}).get("actions") or [])
        if not actions or actions <= {"no-op", "read"}:
            continue
        types.add(str(rc.get("type") or "unknown"))
        if actions in _REPLACE:
            counts["replace"] += 1
        elif actions == {"delete"}:
            counts["destroy"] += 1
        elif actions == {"create"}:
            counts["add"] += 1
        else:
            counts["change"] += 1
    return PlanSummary(
        add=counts["add"],
        change=counts["change"],
        destroy=counts["destroy"],
        replace=counts["replace"],
        resource_types=tuple(sorted(types)),
    )


@dataclass(frozen=True)
class PlanFacts:
    """What the gate and the rubric are told about a PR's plan."""

    status: str  # ok | unavailable
    reason: str = ""
    summary: PlanSummary = field(default_factory=PlanSummary)

    @property
    def clean(self) -> bool:
        return self.status == "ok" and not self.summary.destroy and not self.summary.replace

    def as_fact(self) -> dict[str, Any]:
        return {"status": self.status, "reason": self.reason, **self.summary.as_dict()}


def check_run_payload(
    head_sha: str,
    summary: PlanSummary | None,
    *,
    failure: str = "",
    details_url: str = "",
) -> dict[str, Any]:
    """The body CI POSTs to `/repos/{o}/{r}/check-runs`: the shape read below.

    Written next to `facts_from_check_runs` so the writer and the reader of
    `output.text` are one module, and seeded into the GitOps repo verbatim.
    A plan that ran concludes `success` even with destroys - the conclusion
    says the plan is trustworthy, the counts say what it does, and the gate
    decides. A plan that did not run concludes `failure` with no summary.
    """
    if summary is None or failure:
        reason = failure or "terraform plan did not produce a plan"
        output = {"title": "tf-plan: no plan", "summary": reason, "text": ""}
        conclusion = "failure"
    else:
        risky = summary.destroy or summary.replace
        title = (
            f"tf-plan: +{summary.add} ~{summary.change} -{summary.destroy} ±{summary.replace}"
        )
        types = ", ".join(summary.resource_types) or "none"
        output = {
            "title": title,
            "summary": (
                f"{summary.add} to add, {summary.change} to change, "
                f"{summary.destroy} to destroy, {summary.replace} to replace. "
                f"Resource types: {types}."
                + (" A destroy or replace always asks a human." if risky else "")
            ),
            "text": json.dumps(summary.as_dict(), sort_keys=True),
        }
        conclusion = "success"
    payload: dict[str, Any] = {
        "name": CHECK_NAME,
        "head_sha": head_sha,
        "status": "completed",
        "conclusion": conclusion,
        "output": output,
    }
    if details_url:
        payload["details_url"] = details_url
    return payload


def facts_from_check_runs(runs: list[dict[str, Any]], head_sha: str) -> PlanFacts:
    """The newest `tf-plan` run on the PR head, read fail-closed."""
    current = [r for r in runs if r.get("head_sha") in (None, head_sha)]
    if not current:
        return PlanFacts("unavailable", "no tf-plan check on the PR head")
    run = current[0]
    if run.get("status") != "completed":
        return PlanFacts("unavailable", f"the tf-plan check is {run.get('status')}")
    if run.get("conclusion") != "success":
        return PlanFacts("unavailable", f"the tf-plan check concluded {run.get('conclusion')}")
    text = str((run.get("output") or {}).get("text") or "")
    try:
        raw = json.loads(text)
        summary = PlanSummary(
            add=int(raw["add"]),
            change=int(raw["change"]),
            destroy=int(raw["destroy"]),
            replace=int(raw["replace"]),
            resource_types=tuple(str(t) for t in raw.get("resource_types") or []),
        )
    except (ValueError, KeyError, TypeError):
        return PlanFacts("unavailable", "the tf-plan check carries no readable summary")
    return PlanFacts("ok", summary=summary)
