"""Resource limits checked before a part is loaded, voxelised or simulated.

The solver's memory grows faster than linearly with the element count: about 2 GB of RAM at
29k elements and about 20 GB at 234k (measured on the NIST bridges, docs/results/
mesh_convergence.json). A huge STL or a tiny voxel pitch, for instance requested by an LLM
through the MCP server, could otherwise exhaust the machine's memory. Each limit fails with a
clear error naming the environment variable that raises it.

    PREWARP_MAX_STL_MB      STL file size                     (default 100 MB)
    PREWARP_MAX_ELEMENTS    hexahedral elements per mesh      (default 100 000, ~8 GB)
    PREWARP_MAX_GRID_CELLS  voxel grid cells (bounding box)   (default 20 x max elements)

The grid limit is checked before voxelisation, which allocates the whole bounding-box grid.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np

DEFAULT_MAX_STL_MB = 100.0
DEFAULT_MAX_ELEMENTS = 100_000
GRID_CELLS_PER_ELEMENT = 20


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
