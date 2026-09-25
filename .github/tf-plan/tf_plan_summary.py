#!/usr/bin/env python3
"""Summarise `terraform show -json` for the `tf-plan` check run (#67).

The one program the GitOps repo's `tf-plan` workflow runs to count a plan and
shape its check run. `sandbox.sh seed` copies this file and
`src/sre_agent/review/plan_facts.py` side by side into `.github/tf-plan/`,
so CI counts with the module the agent reads with; the contract test runs
this file from that layout. Standard library only: CI has no `sre_agent`.

    tf_plan_summary.py [plan.json ...]            # summary JSON (stdin if none)
    tf_plan_summary.py --check-run --head-sha SHA [--failed REASON] [plan.json ...]
                                                  # the check-run POST body
    tf_plan_summary.py --assert-stub plan.json    # exit 1 unless null/builtin only

`--assert-stub` guards the one apply the bench workflow does - building the
base branch's local state for a stub module - so a real provider added to
the stub fails the job instead of being applied.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

# What a stub may use: the null provider and the built-in terraform_data.
STUB_PROVIDERS = frozenset(
    {"registry.terraform.io/hashicorp/null", "terraform.io/builtin/terraform"}
)


def _plan_facts() -> ModuleType:
    """plan_facts.py beside this file (the GitOps repo), else in this repo's src."""
    here = Path(__file__).resolve().parent
    for path in (here / "plan_facts.py", here.parent / "src/sre_agent/review/plan_facts.py"):
        if path.is_file():
            spec = importlib.util.spec_from_file_location("plan_facts", path)
            if spec is None or spec.loader is None:  # pragma: no cover
                break
            module = importlib.util.module_from_spec(spec)
            # dataclasses resolve annotations through sys.modules.
            sys.modules["plan_facts"] = module
            spec.loader.exec_module(module)
            return module
    raise SystemExit("plan_facts.py not found next to tf_plan_summary.py")


def merge_plans(docs: list[dict[str, Any]]) -> dict[str, Any]:
    """Several stacks' plans as one: the gate reads one summary per PR."""
    changes: list[Any] = []
    for doc in docs:
        changes.extend(doc.get("resource_changes") or [])
    return {"resource_changes": changes}


def non_stub_providers(doc: dict[str, Any]) -> list[str]:
    """Providers a plan uses that a stub must not - any at all fails the guard."""
    seen = {str(rc.get("provider_name") or "") for rc in doc.get("resource_changes") or []}
    return sorted(seen - STUB_PROVIDERS)


def _load(paths: list[str]) -> list[dict[str, Any]]:
    if not paths:
        return [json.load(sys.stdin)]
    return [json.loads(Path(p).read_text()) for p in paths]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Summarise terraform show -json for the tf-plan check run."
    )
    parser.add_argument("plans", nargs="*", help="`terraform show -json` files")
    parser.add_argument("--check-run", action="store_true", help="print the check-run body")
    parser.add_argument("--head-sha", default="", help="the PR head SHA the check belongs on")
    parser.add_argument("--failed", default="", help="the plan did not run: why")
    parser.add_argument("--details-url", default="", help="link to the CI run")
    parser.add_argument("--assert-stub", action="store_true", help="refuse non-stub providers")
    args = parser.parse_args(argv)
    facts = _plan_facts()

    if args.assert_stub:
        bad = [p for doc in _load(args.plans) for p in non_stub_providers(doc)]
        if bad:
            print(f"not a stub: providers {', '.join(sorted(set(bad)))}", file=sys.stderr)
            return 1
        return 0

    if args.check_run:
        if not args.head_sha:
            parser.error("--check-run needs --head-sha")
        summary = None
        failure = args.failed
        if not failure:
            try:
                summary = facts.summarise_plan(merge_plans(_load(args.plans)))
            except (OSError, ValueError, AttributeError, TypeError) as exc:
                failure = f"the plan could not be read: {type(exc).__name__}"
        payload = facts.check_run_payload(
            args.head_sha, summary, failure=failure, details_url=args.details_url
        )
        print(json.dumps(payload, sort_keys=True))
        return 0

    summary = facts.summarise_plan(merge_plans(_load(args.plans)))
    print(json.dumps(summary.as_dict(), sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
