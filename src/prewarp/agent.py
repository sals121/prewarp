"""PreWarp engineering agent (Claude + tool use) with a numeric grounding gate.

    uv run prewarp agent "My Ti6Al4V bracket.stl warps at the tip — what can I do?"

Claude plans and explains; the PreWarp solver is the only source of numbers.
After the agent answers, ``prewarp.grounding`` checks every number in the answer
against the tool outputs; if any number is unsupported, the agent gets one
chance to correct itself, and anything still unsupported is shown to the user.
"""

from __future__ import annotations

import json
import sys

import anthropic
from anthropic import beta_tool

from . import service
from .grounding import check

MODEL = "claude-opus-5-5"

SYSTEM = """\
You are PreWarp, an additive-manufacturing process engineer assistant for metal laser
powder-bed fusion (LPBF/SLM). You have a finite-element distortion solver as tools.

How to work:
- Use the tools to answer. Typical flow: analyze_part → (rank_orientations if the user can
  change orientation) → compensate_part when they want a printable fix.
- Every number you state must be copied from a tool result, rounded at most, and written
  with its unit and the name of the quantity it measures ("max deviation 0.027 mm", not
  "0.027"). Do not compute new numbers (no ratios, differences or percentages of your own);
  if a tool did not report it, say you don't have it. An automatic check rejects numbers
  that are unbound, mis-converted or attached to the wrong quantity.
- Relay calibration warnings. Say that results are predictions and that a verification print
  is the way to confirm them before production.
- Answer in the user's language. Be concise and practical: what happens, why, what to do,
  and where the output files are."""

_tool_log: list[dict] = []


def _record(result: dict) -> str:
    _tool_log.append(result)
    return json.dumps(result)


@beta_tool
def list_materials() -> str:
    """List supported alloys, elastic constants and inherent-strain calibration status."""
    return _record(service.list_materials())


@beta_tool
def analyze_part(stl_path: str, material: str = "IN718", removal: str = "full") -> str:
    """Predict distortion and residual stress of an STL printed by LPBF/SLM.

    Args:
        stl_path: Path to the part STL in mm, z is the build direction.
        material: Alloy key, e.g. IN718, IN625, Ti6Al4V, 316L, AlSi10Mg.
        removal: "full" if the part is cut off the plate (reported after best-fit alignment), "none" if it stays on the plate.
    """
    return _record(service.analyze_part(stl_path, material=material, removal=removal))


@beta_tool
def compensate_part(stl_path: str, material: str = "IN718", removal: str = "full") -> str:
    """Write a pre-deformed STL that prints and springs back to the nominal CAD; returns before/after deviation and the file path.

    Args:
        stl_path: Path to the part STL in mm.
        material: Alloy key.
        removal: "full" or "none", as in analyze_part.
    """
    return _record(service.compensate_part(stl_path, material=material, removal=removal))


@beta_tool
def rank_orientations(stl_path: str, material: str = "IN718") -> str:
    """Screen six standard build orientations on a coarse mesh and rank them by predicted distortion.

    Args:
        stl_path: Path to the part STL in mm.
        material: Alloy key.
    """
    return _record(service.rank_orientations(stl_path, material=material))


@beta_tool
def nist_validation() -> str:
    """PreWarp's measured accuracy against NIST AM-Bench bridge deflection data."""
    return _record(service.nist_validation_summary())


TOOLS = [list_materials, analyze_part, compensate_part, rank_orientations, nist_validation]


def _final_text(message) -> str:
    return "\n".join(b.text for b in message.content if b.type == "text")


def _run(client: anthropic.Anthropic, messages: list, verbose: bool):
    runner = client.beta.messages.tool_runner(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM,
        tools=TOOLS,
        messages=messages,
        output_config={"effort": "high"},
        # Server-side refusal fallback: a declined turn is retried on a fallback model.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    last = None
    for message in runner:
        last = message
        if verbose:
            for b in message.content:
                if b.type == "tool_use":
                    print(f"  → {b.name}({json.dumps(b.input)})", file=sys.stderr, flush=True)
    return last


def ask(question: str, verbose: bool = True) -> dict:
    """Run the agent on one request; returns answer, grounding report and tool results."""
    _tool_log.clear()
    client = anthropic.Anthropic()
    messages = [{"role": "user", "content": question}]
    last = _run(client, messages, verbose)
    if last.stop_reason == "refusal":
        return {"answer": "The request was declined.", "grounding": None, "tools": list(_tool_log)}
    answer = _final_text(last)
    report = check(answer, _tool_log, user_text=question)
    if not report.ok:  # one self-correction round, citing the exact offending numbers
        messages = [
            *messages,
            {"role": "assistant", "content": last.content},
            {
                "role": "user",
                "content": "Grounding check failed for these numbers:\n"
                + "\n".join(f"- {f.token}: {f.reason}" for f in report.details)
                + "\nRewrite the answer using only tool-reported values, each with its unit and quantity.",
            },
        ]
        last = _run(client, messages, verbose)
        answer = _final_text(last)
        report = check(answer, _tool_log, user_text=question)
    return {"answer": answer, "grounding": report, "tools": list(_tool_log)}


def main(argv: list[str] | None = None) -> None:
    question = " ".join(argv if argv is not None else sys.argv[1:]).strip()
    if not question:
        print('usage: prewarp agent "question about your part.stl"')
        raise SystemExit(2)
    out = ask(question)
    print(out["answer"])
    if out["grounding"] is not None:
        print("\n" + out["grounding"].as_text())


if __name__ == "__main__":
    main()
