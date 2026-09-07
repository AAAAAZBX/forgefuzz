from __future__ import annotations

import argparse
import json
from pathlib import Path

from .engine import Campaign, CampaignConfig
from .loading import available_adapters, load_adapter
from .model import Graph
from .scaffold import create_adapter_project


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="forgefuzz")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run a fuzz campaign")
    run.add_argument(
        "--adapter", default="python",
        help="builtin/entry-point name or module.path:AdapterClass",
    )
    run.add_argument("--iterations", type=int, default=10)
    run.add_argument("--seed", type=int, default=0)
    run.add_argument("--timeout", type=float, default=30.0)
    run.add_argument("--metamorphic-variants", type=int, default=1)
    run.add_argument("--output", type=Path, default=Path("runs/latest"))
    replay = sub.add_parser("replay", help="replay a saved case or graph.json")
    replay.add_argument("case", type=Path)
    replay.add_argument("--adapter", default="python")
    replay.add_argument("--timeout", type=float, default=30.0)
    replay.add_argument("--output", type=Path)
    init = sub.add_parser("init", help="create a standalone adapter project")
    init.add_argument("directory", type=Path)
    init.add_argument("--adapter-name", required=True)
    sub.add_parser("adapters", help="list builtin and installed adapters")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "init":
        path = create_adapter_project(args.directory, args.adapter_name)
        print(f"created adapter project: {path}")
        return 0
    if args.command == "adapters":
        for name, source in available_adapters():
            print(f"{name}\t{source}")
        return 0
    if args.command == "replay":
        graph_path = args.case if args.case.is_file() else args.case / "graph.json"
        graph = Graph.from_dict(json.loads(graph_path.read_text(encoding="utf-8")))
        output = args.output or graph_path.parent / "replay"
        result = Campaign(
            load_adapter(args.adapter), CampaignConfig(output, 1, 0, args.timeout),
        ).replay(graph)
        print(json.dumps({"kind": result.kind.value, "stage": result.stage, "output": str(output)}, indent=2))
        return 0
    adapter = load_adapter(args.adapter)
    config = CampaignConfig(
        args.output, args.iterations, args.seed, args.timeout,
        metamorphic_variants=args.metamorphic_variants,
    )
    print(json.dumps(Campaign(adapter, config).run(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
