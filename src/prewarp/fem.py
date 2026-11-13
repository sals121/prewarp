"""Vectorised linear-elastic FEM for 8-node hexahedra with eigenstrain loads.

Everything is computed for all elements at once with numpy (chunked to bound
memory). Voigt order: xx, yy, zz, yz, xz, xy with engineering shear strains.
"""

from __future__ import annotations

import numpy as np
import scipy.sparse as sp

from .mesh import HEX_CORNERS

# 2x2x2 Gauss points in the reference cube [-1, 1]^3 (all weights = 1).
_G = 1.0 / np.sqrt(3.0)
GAUSS = np.array([[a, b, c] for c in (-_G, _G) for b in (-_G, _G) for a in (-_G, _G)])
_SIGNS = 2.0 * HEX_CORNERS - 1.0  # (8, 3) natural coordinates of the corners


def _shape_derivatives(points: np.ndarray) -> np.ndarray:
    """dN/dxi at the given natural points -> (P, 8, 3)."""
    p = points[:, None, :]  # (P, 1, 3)
    s = _SIGNS[None, :, :]  # (1, 8, 3)
    f = 1.0 + s * p  # (P, 8, 3): (1 + s_i xi_i) factors
    d = np.empty((points.shape[0], 8, 3))
    d[..., 0] = s[..., 0] * f[..., 1] * f[..., 2] / 8.0
    d[..., 1] = f[..., 0] * s[..., 1] * f[..., 2] / 8.0
    d[..., 2] = f[..., 0] * f[..., 1] * s[..., 2] / 8.0
    return d


DN_GAUSS = _shape_derivatives(GAUSS)  # (8 gauss, 8 nodes, 3)
DN_CENTER = _shape_derivatives(np.zeros((1, 3)))  # (1, 8, 3)


def elasticity_matrix(E: float, nu: float) -> np.ndarray:
    """Isotropic 6x6 constitutive matrix (MPa if E in MPa)."""
    lam = E * nu / ((1 + nu) * (1 - 2 * nu))
    mu = E / (2 * (1 + nu))
    D = np.zeros((6, 6))
    D[:3, :3] = lam
    D[np.arange(3), np.arange(3)] = lam + 2 * mu
    D[np.arange(3, 6), np.arange(3, 6)] = mu
    return D


def _b_matrices(xe: np.ndarray, dn: np.ndarray):
    """Strain-displacement matrices.

    Args:
        xe: (E, 8, 3) element node coordinates.
        dn: (P, 8, 3) shape derivatives at P natural points.
    Returns:
        B (E, P, 6, 24) and detJ (E, P).
    """
    J = np.einsum("pnj,eni->epji", dn, xe)  # J[j, i] = d x_i / d xi_j
    detJ = np.linalg.det(J)
    if np.any(detJ <= 0):
        raise ValueError("inverted or degenerate hexahedron (detJ <= 0)")
    invJ = np.linalg.inv(J)
    dndx = np.einsum("epij,pnj->epni", invJ, dn)  # (E, P, 8, 3)
    E, P = dndx.shape[:2]
    B = np.zeros((E, P, 6, 24))
    dx, dy, dz = dndx[..., 0], dndx[..., 1], dndx[..., 2]
    B[..., 0, 0::3] = dx
    B[..., 1, 1::3] = dy
    B[..., 2, 2::3] = dz
    B[..., 3, 1::3] = dz
    B[..., 3, 2::3] = dy
    B[..., 4, 0::3] = dz
    B[..., 4, 2::3] = dx
    B[..., 5, 0::3] = dy
    B[..., 5, 1::3] = dx
    return B, detJ


def _g_matrices(xe: np.ndarray, detJ: np.ndarray) -> np.ndarray:
    """Wilson–Taylor incompatible-mode strain matrices G (E, P, 6, 9).

    Bubble functions (1-ξ²), (1-η²), (1-ζ²) per direction; Taylor's
    correction (Jacobian frozen at the centre, scaled by detJ0/detJ) makes
    ∫G dV = 0 so the element still passes the constant-strain patch test.
    """
    J0 = np.einsum("pnj,eni->epji", DN_CENTER, xe)[:, 0]  # (E, 3, 3)
    detJ0 = np.linalg.det(J0)
    invJ0 = np.linalg.inv(J0)
    # dP_k/dxi_j at gauss points: diagonal -2 xi_k
    dp = np.zeros((GAUSS.shape[0], 3, 3))
    for k in range(3):
        dp[:, k, k] = -2.0 * GAUSS[:, k]
    dpdx = np.einsum("eij,pkj->epki", invJ0, dp)  # (E, P, 3 modes, 3)
    dpdx = dpdx * (detJ0[:, None] / detJ)[:, :, None, None]
    E, P = dpdx.shape[:2]
    G = np.zeros((E, P, 6, 9))
    dx, dy, dz = dpdx[..., 0], dpdx[..., 1], dpdx[..., 2]
    G[..., 0, 0::3] = dx
    G[..., 1, 1::3] = dy
    G[..., 2, 2::3] = dz
    G[..., 3, 1::3] = dz
    G[..., 3, 2::3] = dy
    G[..., 4, 0::3] = dz
    G[..., 4, 2::3] = dx
    G[..., 5, 0::3] = dy
    G[..., 5, 1::3] = dx
    return G


def element_arrays(nodes, elems, D, eigenstrain=None, chunk: int = 3000, incompatible: bool = True):
    """Element stiffness matrices and eigenstrain load vectors.

    Args:
        nodes: (N, 3) node coordinates.
        elems: (E, 8) connectivity.
        D: (6, 6) elasticity matrix.
        eigenstrain: (6,) or (E, 6) inherent strain in Voigt form, or None.
        incompatible: use Wilson–Taylor incompatible modes (statically
            condensed). Removes shear locking in bending — essential for
            distortion, which is bending-dominated.
    Returns:
        Ke (E, 24, 24) and fe (E, 24) — fe is the equivalent nodal load
        ``∫ Bᵀ D ε* dV`` that the eigenstrain exerts.
    """
    n_e = elems.shape[0]
    Ke = np.empty((n_e, 24, 24))
    fe = np.zeros((n_e, 24))
    eps = None
    if eigenstrain is not None:
        eps = np.broadcast_to(np.asarray(eigenstrain, dtype=float), (n_e, 6))
    for s in range(0, n_e, chunk):
        sl = slice(s, min(s + chunk, n_e))
        xe = nodes[elems[sl]]
        B, detJ = _b_matrices(xe, DN_GAUSS)
        DB = np.einsum("ij,epjk->epik", D, B)
        k_uu = np.einsum("epji,epjk,ep->eik", B, DB, detJ)
        sig = eps[sl] @ D.T if eps is not None else None  # (e, 6)
        f_u = np.einsum("epji,ej,ep->ei", B, sig, detJ) if sig is not None else None
        if incompatible:
            G = _g_matrices(xe, detJ)
            DG = np.einsum("ij,epjk->epik", D, G)
            k_ua = np.einsum("epji,epjk,ep->eik", B, DG, detJ)  # (e, 24, 9)
            k_aa = np.einsum("epji,epjk,ep->eik", G, DG, detJ)  # (e, 9, 9)
            rhs = k_ua.transpose(0, 2, 1)
            if sig is not None:
                f_a = np.einsum("epji,ej,ep->ei", G, sig, detJ)
                rhs = np.concatenate([rhs, f_a[:, :, None]], axis=2)
            sol = np.linalg.solve(k_aa, rhs)  # (e, 9, 24[+1])
            k_uu = k_uu - k_ua @ sol[:, :, :24]
            if sig is not None:
                f_u = f_u - np.einsum("eij,ej->ei", k_ua, sol[:, :, 24])
        Ke[sl] = 0.5 * (k_uu + k_uu.transpose(0, 2, 1))
        if f_u is not None:
            fe[sl] = f_u
    return Ke, fe


def element_dofs(elems: np.ndarray) -> np.ndarray:
    """(E, 24) global DOF indices, interleaved x, y, z per node."""
    return (3 * elems[:, :, None] + np.arange(3)[None, None, :]).reshape(-1, 24)


def assemble_matrix(Ke: np.ndarray, dofs: np.ndarray, n_dof: int) -> sp.csr_matrix:
    rows = np.repeat(dofs, 24, axis=1).ravel()
    cols = np.tile(dofs, (1, 24)).ravel()
    K = sp.coo_matrix((Ke.ravel(), (rows, cols)), shape=(n_dof, n_dof)).tocsr()
    K.sum_duplicates()
    return K


def assemble_vector(fe: np.ndarray, dofs: np.ndarray, n_dof: int) -> np.ndarray:
    return np.bincount(dofs.ravel(), weights=fe.ravel(), minlength=n_dof)


def solve_constrained(K: sp.csr_matrix, f: np.ndarray, fixed: np.ndarray, active=None) -> np.ndarray:
    """Solve K u = f with u = 0 on ``fixed`` DOFs.

    Args:
        active: optional boolean mask of DOFs that exist (others stay zero).
    """
    n = K.shape[0]
    free = np.ones(n, dtype=bool) if active is None else active.copy()
    free[fixed] = False
    idx = np.flatnonzero(free)
    u = np.zeros(n)
    if idx.size == 0:
        return u
    from . import linsolve

    u[idx] = linsolve.solve(K[idx][:, idx], f[idx])
    return u


def element_strain_center(nodes, elems, u_nodes) -> np.ndarray:
    """Total strain at element centres (E, 6) from nodal displacements (N, 3)."""
    B, _ = _b_matrices(nodes[elems], DN_CENTER)
    ue = u_nodes[elems].reshape(-1, 24)
    return np.einsum("eij,ej->ei", B[:, 0], ue)


def von_mises(stress: np.ndarray) -> np.ndarray:
    s = stress
    return np.sqrt(
        0.5 * ((s[:, 0] - s[:, 1]) ** 2 + (s[:, 1] - s[:, 2]) ** 2 + (s[:, 2] - s[:, 0]) ** 2)
        + 3.0 * (s[:, 3] ** 2 + s[:, 4] ** 2 + s[:, 5] ** 2)
    )
