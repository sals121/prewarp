"""Sparse SPD solver: Intel MKL PARDISO when available, SciPy SuperLU otherwise.

SuperLU fills in badly on 3-D elasticity (≈10x more memory and minutes instead
of seconds at 1e5 DOF), so PARDISO is the default whenever it is installed.
"""

from __future__ import annotations

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla

try:  # pragma: no cover - depends on platform wheels
    import pypardiso

    BACKEND = "pardiso"
except Exception:  # pragma: no cover
    pypardiso = None
    BACKEND = "superlu"


def solve(A: sp.spmatrix, b: np.ndarray) -> np.ndarray:
    """Solve A x = b for one or several right-hand sides (columns of b)."""
    if pypardiso is not None:
        x = pypardiso.spsolve(sp.csr_matrix(A), np.ascontiguousarray(b))
        if hasattr(pypardiso, "ps"):
            pypardiso.ps.free_memory(everything=True)
        return x
    lu = spla.splu(sp.csc_matrix(A), permc_spec="MMD_AT_PLUS_A")
    return lu.solve(b)
