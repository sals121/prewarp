"""PreWarp as an MCP server (stdio).

Exposes the distortion solver to any MCP client — Claude Desktop, Claude Code,
or your own agent — with no API key needed on the server side.

    uv run prewarp-mcp            # or: python -m prewarp.mcp_server

Claude Code:  claude mcp add prewarp -- uv --directory /path/to/PreWarp run prewarp-mcp
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from . import service
from .paths import checked_stl_path

INSTRUCTIONS = """\
PreWarp predicts distortion of metal laser powder-bed fusion (LPBF/SLM) parts with an
inherent-strain finite-element solver and writes compensated (pre-deformed) STLs.
Rules: every number you report must come from a tool result — never estimate distortion,
stress or improvement yourself. Mention calibration warnings returned by tools. Results are
model predictions; recommend a verification print for production use."""

mcp = MCPServer(name="prewarp", instructions=INSTRUCTIONS)


@mcp.tool()
def list_materials() -> dict:
    """List supported alloys, their elastic constants and inherent-strain calibration status."""
    return service.list_materials()


@mcp.tool()
def analyze_part(
    stl_path: str,
    material: str = "IN718",
    removal: str = "full",
    pitch_mm: float | None = None,
) -> dict:
    """Predict distortion and residual stress of an STL printed by LPBF/SLM.

    Args:
        stl_path: path to the part STL (mm, z = build direction), inside PREWARP_ALLOWED_DIRS.
        material: alloy key from list_materials (e.g. IN718, IN625, Ti6Al4V, 316L, AlSi10Mg).
        removal: "full" = cut off the plate, deviation after best-fit alignment;
            "none" = still on the plate (as-built).
        pitch_mm: voxel size; omit for an automatic laptop-friendly size.
    Returns max/RMS displacement, peak and p95 von Mises stress, a render path and warnings.
    Takes ~10-120 s depending on part size.
    """
    return service.analyze_part(checked_stl_path(stl_path), material=material, removal=removal, pitch_mm=pitch_mm)


@mcp.tool()
def compensate_part(
    stl_path: str,
    material: str = "IN718",
    removal: str = "full",
    pitch_mm: float | None = None,
    iterations: int = 4,
) -> dict:
    """Generate a pre-deformed STL that prints and springs back to the nominal CAD.

    Returns predicted max deviation before/after, reduction %, iteration history and the
    path of the compensated STL. Slower than analyze_part (one solve per iteration).
    """
    return service.compensate_part(
        checked_stl_path(stl_path), material=material, removal=removal, pitch_mm=pitch_mm, iterations=iterations
    )


@mcp.tool()
def rank_orientations(stl_path: str, material: str = "IN718", orientations: list[list[float]] | None = None) -> dict:
    """Screen build orientations [[rx_deg, ry_deg], ...] on a coarse mesh and rank them by
    predicted distortion; also reports build height and plate contact area. Orientations that
    would need supports (floating regions) are listed as infeasible."""
    return service.rank_orientations(checked_stl_path(stl_path), material=material, orientations=orientations)


@mcp.tool()
def nist_validation() -> dict:
    """How accurate is PreWarp? Returns its errors against NIST AM-Bench 2018/2022 measured
    bridge deflections (calibrated fit, held-out points, and blind cross-machine transfer)."""
    return service.nist_validation_summary()


def main() -> None:
    mcp.run("stdio")


if __name__ == "__main__":
    main()
