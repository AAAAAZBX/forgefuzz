from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
from datetime import datetime, timezone
from typing import Any

from . import __version__
from .backends.ascendc import AscendCBackend
from .backends.triton import TritonBackend
from .bundle import CaseBundle, atomic_json, case_lock, sha256_file
from .config import load_config, validate_backend_config
from .doctor import print_doctor, run_doctor
from .pipeline import ALL_STAGES, STAGES, execute_stage, run_pipeline


BACKENDS = {item.name: item for item in (TritonBackend(), AscendCBackend())}


def _add_common_config(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", type=Path, help="JSON or TOML config file")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--timeout", type=float)
    parser.add_argument("--device", choices=("npu", "cpu", "sim", "interpreter"))
    parser.add_argument("--oracle-mode", choices=("auto", "metamorphic", "cpu_npu", "compile_diff", "golden", "external", "torch"))
    parser.add_argument("--comparison", choices=("exact", "allclose"))
    parser.add_argument("--atol", type=float)
    parser.add_argument("--rtol", type=float)
    parser.add_argument("--triton-root", type=Path)
    parser.add_argument("--triton-python", type=Path)
    parser.add_argument("--ascendc-root", type=Path)
    parser.add_argument("--cann-path", type=Path)
    parser.add_argument("--set", action="append", default=[], metavar="KEY=JSON", help="override any advanced config key")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="forgefuzz", description="Unified Triton and AscendC fuzz pipeline")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="create and execute a new case")
    run.add_argument("--backend", choices=BACKENDS, required=True)
    run.add_argument("--seed", type=int, required=True)
    run.add_argument("--case-id")
    run.add_argument("--profile", help="Triton profile, e.g. P1")
    run.add_argument("--template", help="Triton template")
    run.add_argument("--nodes", type=int, help="AscendC graph node count")
    run.add_argument("--ops", help="AscendC comma-separated operation allowlist")
    run.add_argument("--reference-output", type=Path)
    _add_common_config(run)

    sub.add_parser("create", parents=[run], add_help=False, help="create an empty case for step-by-step execution")

    campaign = sub.add_parser("campaign", help="run a sequential range of isolated cases")
    campaign.add_argument("--backend", choices=BACKENDS, required=True)
    campaign.add_argument("--start-seed", type=int, default=0)
    campaign.add_argument("--count", type=int, required=True)
    campaign.add_argument("--campaign-id")
    campaign.add_argument("--stop-on-failure", action="store_true")
    campaign.add_argument("--profile", help="Triton profile, e.g. P1")
    campaign.add_argument("--template", help="Triton template")
    campaign.add_argument("--nodes", type=int, help="AscendC graph node count")
    campaign.add_argument("--ops", help="AscendC comma-separated operation allowlist")
    campaign.add_argument("--reference-output", type=Path)
    _add_common_config(campaign)

    stage = sub.add_parser("stage", help="run exactly one stage for an existing case")
    stage.add_argument("stage", choices=ALL_STAGES)
    stage.add_argument("case_dir", type=Path)

    resume = sub.add_parser("resume", help="continue an existing case from a stage")
    resume.add_argument("case_dir", type=Path)
    resume.add_argument("--from", dest="from_stage", choices=STAGES, required=True)

    replay = sub.add_parser("replay", help="create a fresh case from persisted seed/config")
    replay.add_argument("case_dir", type=Path)

    doctor = sub.add_parser("doctor", help="diagnose projects, dependencies and devices")
    doctor.add_argument("--backend", choices=BACKENDS, help="limit checks to one backend")
    _add_common_config(doctor)
    return parser


def _advanced(values: list[str]) -> dict[str, Any]:
    result = {}
    for item in values:
        if "=" not in item:
            raise ValueError(f"--set requires KEY=JSON, got {item!r}")
        key, raw = item.split("=", 1)
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            value = raw
        result[key] = value
    return result


def _resolved(args: argparse.Namespace) -> dict[str, Any]:
    overrides = _advanced(getattr(args, "set", []))
    mapping = {
        "output_dir": str(args.output_dir.resolve()) if getattr(args, "output_dir", None) else None,
        "timeout": getattr(args, "timeout", None),
        "device": getattr(args, "device", None),
        "oracle_mode": getattr(args, "oracle_mode", None),
        "comparison": getattr(args, "comparison", None),
        "atol": getattr(args, "atol", None),
        "rtol": getattr(args, "rtol", None),
        "triton_root": str(args.triton_root.resolve()) if getattr(args, "triton_root", None) else None,
        "triton_python": str(args.triton_python.resolve()) if getattr(args, "triton_python", None) else None,
        "ascendc_root": str(args.ascendc_root.resolve()) if getattr(args, "ascendc_root", None) else None,
        "ascend_cann_path": str(args.cann_path.resolve()) if getattr(args, "cann_path", None) else None,
        "triton_profile": getattr(args, "profile", None),
        "triton_template": getattr(args, "template", None),
        "ascend_nodes": getattr(args, "nodes", None),
        "ascend_ops": getattr(args, "ops", None),
        "reference_output": str(args.reference_output.resolve()) if getattr(args, "reference_output", None) else None,
    }
    overrides.update({key: value for key, value in mapping.items() if value is not None})
    config = load_config(getattr(args, "config", None), overrides)
    if getattr(args, "device", None) in {"npu", "cpu", "sim"}:
        config["ascend_run_mode"] = args.device
    return config


def _case_id(backend: str, seed: int) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"case-{backend}-{seed}-{timestamp}"


def _success(ctx) -> bool:
    return all(ctx.results.get(stage) and ctx.results[stage].success for stage in STAGES)


def _print_results(ctx) -> None:
    for stage in ALL_STAGES:
        if stage in ctx.results:
            result = ctx.results[stage]
            print(f"[{'PASS' if result.success else 'FAIL'}] {stage}: {result.message}")
    print(f"case: {ctx.work_dir}")


def command_run(args: argparse.Namespace) -> int:
    config = _resolved(args)
    validate_backend_config(config, args.backend)
    output = Path(config["output_dir"])
    output.mkdir(parents=True, exist_ok=True)
    case_id = args.case_id or _case_id(args.backend, args.seed)
    ctx = CaseBundle.create(output, case_id, args.backend, args.seed, config)
    if args.command == "create":
        print(f"case: {ctx.work_dir}")
        return 0
    with case_lock(ctx.work_dir):
        run_pipeline(BACKENDS[args.backend], ctx)
    _print_results(ctx)
    return 0 if _success(ctx) else 1


def command_campaign(args: argparse.Namespace) -> int:
    if args.count <= 0:
        raise ValueError("campaign count must be positive")
    config = _resolved(args)
    validate_backend_config(config, args.backend)
    root = Path(config["output_dir"])
    root.mkdir(parents=True, exist_ok=True)
    campaign_id = args.campaign_id or f"campaign-{args.backend}-{_case_id(args.backend, args.start_seed).split('-', 3)[-1]}"
    if not campaign_id or not all(character.isalnum() or character in "-_" for character in campaign_id):
        raise ValueError("campaign ID may contain only letters, digits, '-' and '_'")
    campaign_dir = root / campaign_id
    cases_dir = campaign_dir / "cases"
    cases_dir.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    summary: dict[str, Any] = {
        "schema_version": 1,
        "campaign_id": campaign_id,
        "backend": args.backend,
        "start_seed": args.start_seed,
        "requested_count": args.count,
        "stop_on_failure": args.stop_on_failure,
        "status": "running",
        "cases": [],
    }
    summary_path = campaign_dir / "campaign.json"
    atomic_json(summary_path, summary)
    for offset in range(args.count):
        seed = args.start_seed + offset
        case_id = f"case-{args.backend}-{seed}"
        ctx = CaseBundle.create(cases_dir, case_id, args.backend, seed, config)
        with case_lock(ctx.work_dir):
            run_pipeline(BACKENDS[args.backend], ctx)
        passed = _success(ctx)
        summary["cases"].append({
            "case_id": case_id,
            "seed": seed,
            "status": "passed" if passed else "failed",
            "path": str(ctx.work_dir),
            "failure_stage": next((stage for stage in STAGES if ctx.results.get(stage) and not ctx.results[stage].success), None),
        })
        atomic_json(summary_path, summary)
        print(f"[{'PASS' if passed else 'FAIL'}] seed={seed} case={ctx.work_dir}")
        if not passed and args.stop_on_failure:
            break
    passed_count = sum(item["status"] == "passed" for item in summary["cases"])
    summary.update({
        "status": "passed" if passed_count == len(summary["cases"]) else "failed",
        "executed_count": len(summary["cases"]),
        "passed_count": passed_count,
        "failed_count": len(summary["cases"]) - passed_count,
        "duration_seconds": time.monotonic() - started,
    })
    atomic_json(summary_path, summary)
    print(f"campaign: {campaign_dir}")
    return 0 if summary["failed_count"] == 0 else 1


def _prerequisite(stage: str) -> str | None:
    if stage in {"generate", "report"}:
        return None
    return STAGES[STAGES.index(stage) - 1]


def command_stage(args: argparse.Namespace) -> int:
    with case_lock(args.case_dir):
        ctx = CaseBundle.load(args.case_dir)
        prerequisite = _prerequisite(args.stage)
        if prerequisite and (not ctx.results.get(prerequisite) or not ctx.results[prerequisite].success):
            print(f"cannot run {args.stage}: prerequisite {prerequisite} has not succeeded", file=sys.stderr)
            return 2
        result = execute_stage(BACKENDS[ctx.backend], ctx, args.stage)
        if args.stage != "report":
            execute_stage(BACKENDS[ctx.backend], ctx, "report")
    _print_results(ctx)
    return 0 if result.success else 1


def command_resume(args: argparse.Namespace) -> int:
    with case_lock(args.case_dir):
        ctx = CaseBundle.load(args.case_dir)
        index = STAGES.index(args.from_stage)
        prerequisite = _prerequisite(args.from_stage)
        if prerequisite and (not ctx.results.get(prerequisite) or not ctx.results[prerequisite].success):
            print(f"cannot resume from {args.from_stage}: prerequisite {prerequisite} has not succeeded", file=sys.stderr)
            return 2
        CaseBundle.truncate_results(ctx, STAGES[index:] + ["report"])
        run_pipeline(BACKENDS[ctx.backend], ctx, start_stage=args.from_stage)
    _print_results(ctx)
    return 0 if _success(ctx) else 1


def command_replay(args: argparse.Namespace) -> int:
    with case_lock(args.case_dir):
        original = CaseBundle.load(args.case_dir)
        config = dict(original.config)
        output = original.work_dir.parent
        replay_id = _case_id(original.backend, original.seed) + "-replay"
        config["replay_of"] = str(original.work_dir)
        ctx = CaseBundle.create(output, replay_id, original.backend, original.seed, config)
        old_program = original.work_dir / "program" / ("kernel_spec.json" if original.backend == "triton" else "graph.json")
        old_sha256 = sha256_file(old_program) if old_program.is_file() else None
    with case_lock(ctx.work_dir):
        run_pipeline(BACKENDS[ctx.backend], ctx)
    new_program = ctx.work_dir / "program" / old_program.name
    new_sha256 = sha256_file(new_program) if new_program.is_file() else None
    reproducible = old_sha256 is not None and old_sha256 == new_sha256
    atomic_json(ctx.work_dir / "configs" / "replay.json", {"original": str(original.work_dir), "program_representation_matches": reproducible, "old_sha256": old_sha256, "new_sha256": new_sha256})
    print(f"program representation reproducible: {reproducible}")
    _print_results(ctx)
    return 0 if _success(ctx) and reproducible else 1


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--backend" in argv and (not argv or argv[0] not in {"run", "create", "campaign", "stage", "resume", "replay", "doctor"}):
        argv.insert(0, "run")
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command in {"run", "create"}:
            return command_run(args)
        if args.command == "campaign":
            return command_campaign(args)
        if args.command == "stage":
            return command_stage(args)
        if args.command == "resume":
            return command_resume(args)
        if args.command == "replay":
            return command_replay(args)
        config = _resolved(args)
        checks, healthy = run_doctor(config, backend=getattr(args, "backend", None))
        print_doctor(checks)
        return 0 if healthy else 1
    except (OSError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
