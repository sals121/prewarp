"""Layer-by-layer inherent-strain build simulation and plate-removal springback.

The displacement field is linear in the inherent strain, so the build is solved
once for two unit load cases — in-plane ``(1, 1, 0)`` and vertical ``(0, 0, 1)``
— and any ``(eps_xy, eps_z)`` is a linear combination. That makes calibration
a least-squares problem and parameter sweeps free.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import scipy.sparse as sp
import scipy.sparse.csgraph as csgraph

from .fem import (
    DN_CENTER,
    _b_matrices,
    assemble_matrix,
    assemble_vector,
    element_arrays,
    element_dofs,
    elasticity_matrix,
    von_mises,
)
from . import linsolve
from .mesh import HexMesh

UNIT_CASES = (
    np.array([1.0, 1.0, 0.0, 0.0, 0.0, 0.0]),  # in-plane, isotropic (rotating scan)
    np.array([0.0, 0.0, 1.0, 0.0, 0.0, 0.0]),  # build direction
)


@dataclass
class BuildBasis:
    """Unit-strain responses of one geometry; combine with ``combine``.

    Arrays carry a trailing axis of length 2 = (in-plane, vertical) case.
    """

    mesh: HexMesh
    E: float
    nu: float
    plate_nodes: np.ndarray  # node ids welded to the build plate
    u: np.ndarray  # (N, 3, 2) as-built displacement, part still on plate
    u_act: np.ndarray  # (E, 24, 2) element nodal displacement at activation
    Ke: np.ndarray  # (E, 24, 24)
    fe: np.ndarray  # (E, 24, 2) unit eigenstrain loads
    n_steps: int
    history: list | None = None  # per step: (active element mask, u (N,3,2))
    cases: tuple = UNIT_CASES  # the two unit inherent-strain load cases (Voigt)

    def combine(self, eps_xy: float, eps_z: float) -> np.ndarray:
        return self.u @ np.array([eps_xy, eps_z])

    def elastic_strain(self, eps_xy: float, eps_z: float) -> np.ndarray:
        """Element-centre elastic strain (E, 6), Voigt, part on the plate.

        Total strain accumulated since each element was deposited, minus the
        inherent strain. This is what diffraction measures as lattice strain.
        """
        w = np.array([eps_xy, eps_z])
        B, _ = _b_matrices(self.mesh.nodes[self.mesh.elems], DN_CENTER)
        du = (self.u[self.mesh.elems].reshape(-1, 24, 2) - self.u_act) @ w
        strain = np.einsum("eij,ej->ei", B[:, 0], du)
        return strain - (self.cases[0] * eps_xy + self.cases[1] * eps_z)

    def stress(self, eps_xy: float, eps_z: float) -> np.ndarray:
        """Element-centre residual stress (E, 6) in MPa, part on the plate."""
        return self.elastic_strain(eps_xy, eps_z) @ elasticity_matrix(self.E, self.nu).T


@dataclass
class Release:
    """Springback after cutting the part (fully or partially) off the plate."""

    keep_elems: np.ndarray  # bool (E,) elements that remain after the cut
    node_ids: np.ndarray  # (M,) original node ids of the remaining part
    du: np.ndarray  # (M, 3, 2) springback displacement per unit case
    u_total: np.ndarray  # (M, 3, 2) as-built + springback

    def combine(self, eps_xy: float, eps_z: float) -> np.ndarray:
        return self.u_total @ np.array([eps_xy, eps_z])


def build_layers(mesh: HexMesh, layer_mm: float | None = None) -> np.ndarray:
    """Activation layer of each element, from its *current* centroid height.

    The machine slices the geometry it is given with horizontal planes. For a
    morphed (compensated) mesh the voxel layer index is no longer horizontal, so
    activation order must follow the real z of each element, not its lattice index.

    Args:
        layer_mm: activation layer thickness; default one voxel (``mesh.pitch``).
            The calibrated inherent strain is tied to this thickness.
    """
    h = mesh.pitch if layer_mm is None else float(layer_mm)
    z0 = mesh.nodes[:, 2].min()
    zc = mesh.elem_centers()[:, 2]
    return np.maximum(np.floor((zc - z0) / h + 1e-9), 0).astype(np.int64)


def _layer_groups(layers: np.ndarray, n_steps: int | None) -> list[np.ndarray]:
    lo, hi = int(layers.min()), int(layers.max()) + 1
    n_layers = hi - lo
    n = n_layers if n_steps is None else max(1, min(n_steps, n_layers))
    edges = np.unique(np.round(np.linspace(lo, hi, n + 1)).astype(int))
    return [(layers >= a) & (layers < b) for a, b in zip(edges[:-1], edges[1:])]


def _face_neighbors(mesh: HexMesh) -> sp.csr_matrix:
    """Element-element adjacency through shared faces (lattice neighbours)."""
    ijk = mesh.elem_ijk
    shape = ijk.max(axis=0) + 3
    key = np.ravel_multi_index((ijk + 1).T, shape)
    lut = -np.ones(int(np.prod(shape)), dtype=np.int64)
    lut[key] = np.arange(mesh.n_elems)
    rows, cols = [], []
    for d in np.vstack([np.eye(3, dtype=np.int64), -np.eye(3, dtype=np.int64)]):
        nb = lut[np.ravel_multi_index((ijk + 1 + d).T, shape)]
        ok = nb >= 0
        rows.append(np.flatnonzero(ok))
        cols.append(nb[ok])
    r, c = np.concatenate(rows), np.concatenate(cols)
    return sp.csr_matrix((np.ones(r.size), (r, c)), shape=(mesh.n_elems,) * 2)


def _defer_unsupported(mesh: HexMesh, groups: list[np.ndarray]) -> list[np.ndarray]:
    """A machine cannot print a region that only touches finished material along
    an edge or a corner: it would be deposited on loose powder. At voxel level
    that happens when a morphed (compensated) mesh is sliced horizontally and a
    down-skin row lands one layer ahead of its neighbour. Such patches would act
    as hinges and produce spurious local displacement, so they are moved to the
    next step, where their face neighbour exists."""
    adj = _face_neighbors(mesh)
    on_plate = mesh.elem_ijk[:, 2] == mesh.elem_ijk[:, 2].min()
    active = np.zeros(mesh.n_elems, dtype=bool)
    carry = np.zeros(mesh.n_elems, dtype=bool)
    out: list[np.ndarray] = []
    for i, g in enumerate(groups):
        new = g | carry
        while True:
            ids = np.flatnonzero(new)
            if ids.size == 0:
                break
            n_comp, lab = csgraph.connected_components(adj[ids][:, ids], directed=False)
            touches = on_plate[ids] | (adj[ids] @ active.astype(float) > 0)
            ok_comp = np.zeros(n_comp, dtype=bool)
            ok_comp[lab[touches]] = True
            bad = ids[~ok_comp[lab]]
            if bad.size == 0 or i == len(groups) - 1:
                break
            new[bad] = False
        carry = (g | carry) & ~new
        active |= new
        out.append(new)
    return [g for g in out if g.any()]


def _check_supported(mesh: HexMesh, fixed_nodes: np.ndarray) -> None:
    e = mesh.elems
    rows = np.repeat(e[:, 0], 7)
    cols = e[:, 1:].ravel()
    g = sp.coo_matrix((np.ones(rows.size), (rows, cols)), shape=(mesh.n_nodes,) * 2)
    n_comp, labels = csgraph.connected_components(g, directed=False)
    supported = np.unique(labels[fixed_nodes])
    if supported.size < n_comp:
        raise ValueError(
            f"geometry has {n_comp - supported.size} floating island(s) not connected to the "
            "build plate — add supports or fix the model"
        )


def _solve(K: sp.csr_matrix, rhs: np.ndarray, free: np.ndarray) -> np.ndarray:
    idx = np.flatnonzero(free)
    out = np.zeros_like(rhs)
    if idx.size:
        out[idx] = linsolve.solve(K[idx][:, idx], rhs[idx]).reshape(out[idx].shape)
    return out


def simulate_build(
    mesh: HexMesh,
    E: float,
    nu: float,
    n_steps: int | None = 12,
    progress=None,
    incompatible: bool = True,
    record: bool = False,
    layers: np.ndarray | None = None,
    layer_mm: float | None = None,
    cases: tuple = UNIT_CASES,
) -> BuildBasis:
    """Activate the part bottom-up in ``n_steps`` lumped layer groups.

    Nodes on the lowest node layer are welded to a rigid build plate.
    ``layers`` overrides the per-element build layer (default: real height in
    ``layer_mm`` thick activation layers, see :func:`build_layers`).
    """
    D = elasticity_matrix(E, nu)
    n_dof = 3 * mesh.n_nodes
    dofs = element_dofs(mesh.elems)

    Ke, f_a = element_arrays(mesh.nodes, mesh.elems, D, np.asarray(cases[0], float), incompatible=incompatible)
    _, f_b = element_arrays(mesh.nodes, mesh.elems, D, np.asarray(cases[1], float), incompatible=incompatible)
    fe = np.stack([f_a, f_b], axis=2)

    kmin = mesh.node_ijk[:, 2].min()
    plate = np.flatnonzero(mesh.node_ijk[:, 2] == kmin)
    _check_supported(mesh, plate)
    plate_dof = np.zeros(n_dof, dtype=bool)
    plate_dof[(3 * plate[:, None] + np.arange(3)).ravel()] = True

    groups = _defer_unsupported(mesh, _layer_groups(build_layers(mesh, layer_mm) if layers is None else layers, n_steps))
    u = np.zeros((n_dof, 2))
    u_act = np.zeros((mesh.n_elems, 24, 2))
    K = sp.csr_matrix((n_dof, n_dof))
    active_dof = np.zeros(n_dof, dtype=bool)
    history: list = []

    for s, new in enumerate(groups):
        new_ids = np.flatnonzero(new)
        u_act[new_ids] = u[dofs[new_ids]]  # nodes shared with the layer below
        K = K + assemble_matrix(Ke[new_ids], dofs[new_ids], n_dof)
        active_dof[dofs[new_ids].ravel()] = True
        rhs = np.stack(
            [assemble_vector(fe[new_ids, :, c], dofs[new_ids], n_dof) for c in range(2)], axis=1
        )
        u += _solve(K, rhs, active_dof & ~plate_dof)
        if record:
            done = np.zeros(mesh.n_elems, dtype=bool)
            for g in groups[: s + 1]:
                done |= g
            history.append((done, u.reshape(-1, 3, 2).copy()))
        if progress:
            progress(s + 1, len(groups))

    return BuildBasis(
        mesh=mesh,
        E=E,
        nu=nu,
        plate_nodes=plate,
        u=u.reshape(-1, 3, 2),
        u_act=u_act,
        Ke=Ke,
        fe=fe,
        n_steps=len(groups),
        history=history if record else None,
        cases=tuple(np.asarray(c, float) for c in cases),
    )


def release(basis: BuildBasis, remove_elems: np.ndarray | None = None, keep_fixed_nodes: np.ndarray | None = None) -> Release:
    """Cut the part off the plate and compute the elastic springback.

    Args:
        remove_elems: bool (E,) elements destroyed by the cut (e.g. a wire-EDM
            kerf or the support layer). ``None`` = none removed.
        keep_fixed_nodes: node ids that stay welded to the plate (e.g. one leg
            left attached). ``None`` = part fully free (rigid-body modes are
            removed with a statically determinate 3-2-1 constraint).
    """
    mesh = basis.mesh
    remove = np.zeros(mesh.n_elems, dtype=bool) if remove_elems is None else np.asarray(remove_elems, bool)
    keep = ~remove
    sub, node_ids = mesh.subset(keep)
    remap = -np.ones(mesh.n_nodes, dtype=np.int64)
    remap[node_ids] = np.arange(node_ids.size)

    n_dof = 3 * sub.n_nodes
    dofs = element_dofs(sub.elems)
    Ke = basis.Ke[keep]
    # Internal force of each surviving element: Ke (u_e - u_act_e) - fe
    u_e = basis.u[mesh.elems[keep]].reshape(-1, 24, 2)
    f_int = np.einsum("eij,ejc->eic", Ke, u_e - basis.u_act[keep]) - basis.fe[keep]
    residual = -np.stack([assemble_vector(f_int[:, :, c], dofs, n_dof) for c in range(2)], axis=1)

    if keep_fixed_nodes is not None and len(keep_fixed_nodes):
        fixed_nodes = remap[np.asarray(keep_fixed_nodes)]
        fixed_nodes = fixed_nodes[fixed_nodes >= 0]
        fixed = (3 * fixed_nodes[:, None] + np.arange(3)).ravel()
    else:
        fixed = _three_two_one(sub.nodes)
    free = np.ones(n_dof, dtype=bool)
    free[fixed] = False
    residual[fixed] = 0.0

    K = assemble_matrix(Ke, dofs, n_dof)
    du = _solve(K, residual, free).reshape(-1, 3, 2)
    return Release(keep_elems=keep, node_ids=node_ids, du=du, u_total=basis.u[node_ids] + du)


def _three_two_one(x: np.ndarray) -> np.ndarray:
    """Statically determinate constraint on three well-separated nodes."""
    lo = x.min(axis=0)
    span = x.max(axis=0) - lo
    a = int(np.argmin(np.linalg.norm(x - lo, axis=1)))
    b = int(np.argmin(np.linalg.norm(x - (lo + [span[0], 0, 0]), axis=1)))
    c = int(np.argmin(np.linalg.norm(x - (lo + [0, span[1], 0]), axis=1)))
    return np.array([3 * a, 3 * a + 1, 3 * a + 2, 3 * b + 1, 3 * b + 2, 3 * c + 2])


def summarize(mesh: HexMesh, u: np.ndarray, stress: np.ndarray | None = None, yield_MPa: float = 0.0) -> dict:
    """Headline numbers for reports and the LLM layer."""
    mag = np.linalg.norm(u, axis=1)
    i = int(np.argmax(mag))
    out = {
        "max_displacement_mm": float(mag[i]),
        "max_displacement_at_mm": [float(v) for v in mesh.nodes[i]],
        "max_abs_dz_mm": float(np.abs(u[:, 2]).max()),
        "rms_displacement_mm": float(np.sqrt((mag**2).mean())),
    }
    if stress is not None:
        # The maximum is not reported: re-entrant voxel corners are stress singularities.
        vm = von_mises(stress)
        out["p95_von_mises_MPa"] = float(np.percentile(vm, 95))
        out["p99_von_mises_MPa"] = float(np.percentile(vm, 99))
        if yield_MPa:
            out["volume_fraction_above_yield"] = float((vm > yield_MPa).mean())
    return out
