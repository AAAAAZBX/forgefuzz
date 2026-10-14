from __future__ import annotations

import shlex

from .bundle import CaseBundle, atomic_json, utc_now
from .models import CaseContext, StageResult


CORE_STAGES = ("generate", "emit", "build", "run", "oracle")


def build_report(ctx: CaseContext) -> StageResult:
    failed = next((ctx.results[name] for name in CORE_STAGES if name in ctx.results and not ctx.results[name].success), None)
    complete = all(name in ctx.results for name in CORE_STAGES)
    success = complete and failed is None
    replay_argv = ["forgefuzz", "replay", str(ctx.work_dir)]
    report = {
        "schema_version": 1,
        "case_id": ctx.case_id,
        "backend": ctx.backend,
        "seed": ctx.seed,
        "status": "passed" if success else ("failed" if failed else "incomplete"),
        "failure_stage": failed.stage if failed else None,
        "failure_kind": failed.failure_kind if failed else None,
        "message": failed.message if failed else ("all stages passed" if success else "case is incomplete"),
        "results": {name: result.to_dict() for name, result in ctx.results.items() if name != "report"},
        "manifest": CaseBundle.manifest(ctx),
        "manifest_excludes": ["cache/**", "source/*/{build,input,out,output}/**"],
        "replay": shlex.join(replay_argv),
        "replay_argv": replay_argv,
        "generated_at": utc_now(),
    }
    atomic_json(ctx.work_dir / "report.json", report)
    markdown = [f"# ForgeFuzz case `{ctx.case_id}`", "", f"- Backend: `{ctx.backend}`", f"- Seed: `{ctx.seed}`", f"- Status: `{report['status']}`", f"- Failure stage: `{report['failure_stage'] or 'none'}`", f"- Failure kind: `{report['failure_kind'] or 'none'}`", "", "## Replay", "", "```bash", report["replay"], "```", ""]
    (ctx.work_dir / "report.md").write_text("\n".join(markdown), encoding="utf-8")
    return StageResult.ok("report", f"report written ({report['status']})", artifacts=["report.json", "report.md"], details={"case_success": success})
