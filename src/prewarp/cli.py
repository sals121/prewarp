"""Command-line interface: ``prewarp <command> ...``"""

from __future__ import annotations

import argparse
import json
import sys


def _print(result: dict) -> None:
    print(json.dumps(result, indent=2, ensure_ascii=False))


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "agent":
        from .agent import main as agent_main

        return agent_main(argv[1:])
    if argv and argv[0] == "mcp":
        from .mcp_server import main as mcp_main

        return mcp_main()

    ap = argparse.ArgumentParser(prog="prewarp", description="Predict and compensate LPBF/SLM distortion.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("stl")
        p.add_argument("-m", "--material", default="IN718")
        p.add_argument("--pitch", type=float, default=None, help="voxel size in mm (default: automatic)")
        p.add_argument("--removal", choices=["full", "none"], default="full")
        p.add_argument("--eps-xy", type=float, default=None, help="override calibrated inherent strain")
        p.add_argument("-o", "--output-dir", default=None)

    common(sub.add_parser("analyze", help="predict distortion and residual stress"))
    pc = sub.add_parser("compensate", help="write a pre-deformed STL")
    common(pc)
    pc.add_argument("--iterations", type=int, default=4)
    po = sub.add_parser("orient", help="rank build orientations")
    po.add_argument("stl")
    po.add_argument("-m", "--material", default="IN718")
    sub.add_parser("materials", help="list materials and calibration status")
    sub.add_parser("validation", help="show accuracy vs NIST AM-Bench")
    sub.add_parser("agent", help='ask the Claude agent: prewarp agent "question"')
    sub.add_parser("mcp", help="run the MCP server (stdio)")

    a = ap.parse_args(argv)
    from .limits import ResourceLimitError

    try:
        _run(a)
    except ResourceLimitError as err:
        ap.exit(2, f"prewarp: {err}\n")


def _run(a) -> None:
    from . import service

    if a.cmd == "analyze":
        _print(service.analyze_part(a.stl, a.material, a.pitch, a.removal, a.eps_xy, output_dir=a.output_dir))
    elif a.cmd == "compensate":
        _print(service.compensate_part(a.stl, a.material, a.pitch, a.removal, a.eps_xy,
                                       iterations=a.iterations, output_dir=a.output_dir))
    elif a.cmd == "orient":
        _print(service.rank_orientations(a.stl, a.material))
    elif a.cmd == "materials":
        _print(service.list_materials())
    elif a.cmd == "validation":
        _print(service.nist_validation_summary())


if __name__ == "__main__":
    main()
