"""Resource limits checked before a part is loaded, voxelised or simulated.

The solver's memory grows faster than linearly with the element count: about 2 GB of RAM at
29k elements and about 20 GB at 234k (measured on the NIST bridges, docs/results/
mesh_convergence.json). A huge STL or a tiny voxel pitch, for instance requested by an LLM
through the MCP server, could otherwise exhaust the machine's memory. Each limit fails with a
clear error naming the environment variable that raises it.

    PREWARP_MAX_STL_MB      STL file size                     (default 100 MB)
    PREWARP_MAX_ELEMENTS    hexahedral elements per mesh      (default 100 000, ~8 GB)
    PREWARP_MAX_GRID_CELLS  voxel grid cells (bounding box)   (default 20 x max elements)
    PREWARP_MAX_TRIANGLES   STL triangles, and the triangles  (default 2 000 000)
                            a non-watertight STL is subdivided into before voxelising

The grid and triangle limits are checked before voxelisation: a watertight part allocates the
whole bounding-box grid, a non-watertight one is subdivided until every edge is < pitch / 2.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np

DEFAULT_MAX_STL_MB = 100.0
DEFAULT_MAX_ELEMENTS = 100_000
GRID_CELLS_PER_ELEMENT = 20
DEFAULT_MAX_TRIANGLES = 2_000_000


class ResourceLimitError(ValueError):
    """A part is too large for the configured limits."""


def _env_number(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(f"{name}={raw!r} is not a number") from None
    if value <= 0:
        raise ValueError(f"{name}={raw!r} must be positive")
    return value


def max_stl_mb() -> float:
    return _env_number("PREWARP_MAX_STL_MB", DEFAULT_MAX_STL_MB)


def max_elements() -> int:
    return int(_env_number("PREWARP_MAX_ELEMENTS", DEFAULT_MAX_ELEMENTS))


def max_grid_cells() -> int:
    return int(_env_number("PREWARP_MAX_GRID_CELLS", GRID_CELLS_PER_ELEMENT * max_elements()))


def check_stl_size(path: str | Path) -> None:
    mb = os.path.getsize(path) / 2**20
    if mb > max_stl_mb():
        raise ResourceLimitError(
            f"{Path(path).name}: STL is {mb:.1f} MB, above the {max_stl_mb():g} MB limit "
            "(set PREWARP_MAX_STL_MB to raise it)"
        )


def max_triangles() -> int:
    return int(_env_number("PREWARP_MAX_TRIANGLES", DEFAULT_MAX_TRIANGLES))


def subdivided_triangles(surface, pitch: float) -> int:
    """Triangles trimesh's surface voxeliser would create (used for non-watertight STLs).

    ``voxelize_subdivide`` splits each face 1 -> 4 until every edge is shorter than pitch / 2,
    for at most 10 rounds, so a face whose longest edge is L becomes 4**k faces with
    k = ceil(log2(L / (pitch / 2))) clipped to [0, 10].
    """
    tri = surface.vertices[surface.faces]
    longest = np.max(np.linalg.norm(tri - np.roll(tri, 1, axis=1), axis=2), axis=1)
    k = np.clip(np.ceil(np.log2(np.maximum(longest / (pitch / 2), 1.0))), 0, 10)
    return int(np.sum(4.0**k))


def check_surface(surface, pitch: float) -> None:
    """Triangle count of the STL, and of its subdivision when it is not watertight."""
    n = len(surface.faces)
    if n > max_triangles():
        raise ResourceLimitError(
            f"STL has {n:,} triangles, above the {max_triangles():,} limit "
            "(set PREWARP_MAX_TRIANGLES to raise it)"
        )
    if not surface.is_watertight:
        est = subdivided_triangles(surface, pitch)
        if est > max_triangles():
            raise ResourceLimitError(
                f"the STL is not watertight, and voxelising its surface at {pitch:g} mm would "
                f"create about {est:.3g} triangles, above the {max_triangles():,} limit; repair "
                "the STL, use a coarser pitch or set PREWARP_MAX_TRIANGLES"
            )


def check_grid(bounds: np.ndarray, pitch: float) -> None:
    """Bounding-box voxel count at ``pitch``, before the grid is allocated."""
    if not pitch > 0:
        raise ValueError(f"voxel pitch must be positive, got {pitch}")
    lo, hi = np.asarray(bounds, dtype=float)
    cells = float(np.prod(np.maximum(1, np.ceil((hi - lo) / pitch) + 1)))
    if cells > max_grid_cells():
        raise ResourceLimitError(
            f"voxel pitch {pitch:g} mm gives a {cells:.3g}-cell grid, above the "
            f"{max_grid_cells():,} cell limit; use a coarser pitch or set PREWARP_MAX_GRID_CELLS"
        )


def check_elements(n_elems: int, pitch: float) -> None:
    if n_elems > max_elements():
        raise ResourceLimitError(
            f"voxel pitch {pitch:g} mm gives {n_elems:,} elements, above the {max_elements():,} "
            "element limit (solver memory grows faster than linearly: ~20 GB at 234k); use a "
            "coarser pitch or set PREWARP_MAX_ELEMENTS"
        )
