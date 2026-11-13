"""Geometric distortion compensation (pre-deformation of the CAD).

Fixed-point iteration on node coordinates:

    x_{k+1} = x_k − α · ((x_k + u(x_k)) − x_nominal)

where ``u(x_k)`` is the full predicted distortion (build + springback) of the
mesh *as it would be printed* (re-solved on the morphed mesh every iteration).

The pre-deformed part is sliced by horizontal planes, so its elements are
activated by their real height. That assignment is discrete (one activation
layer = one voxel), so it is computed on the first compensated shape and then
frozen: later corrections are tens of µm, and re-assigning every iteration
makes rows of elements chatter between layers and the iteration stall.
At the end the compensated shape is re-sliced from scratch and simulated once
more; that independent check (``verified``) is the number to trust, and its
displacement is what ``u_compensated`` holds.
Nodes welded to the plate keep their z (the plate is flat). If the part is
fully removed from the plate, deviation is measured after a best-fit rigid
alignment, exactly like a CMM/scan inspection.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import trimesh
from scipy.spatial import cKDTree

from .mesh import HexMesh
from .simulate import build_layers, release, simulate_build


@dataclass
class DistortionModel:
    """Everything needed to predict the final shape of a mesh."""

    E: float
    nu: float
    eps_xy: float
    eps_z: float
    n_steps: int | None = None
    # Selects plate nodes that stay welded after cutting; None = fully removed.
    attached: callable | None = None
    layer_mm: float | None = None  # activation layer thickness (default: one voxel)
    # Unit load cases weighted by (eps_xy, eps_z); swap for e.g. x-only / y-only to
    # model anisotropic inherent strain.
    cases: tuple | None = None

    def final_displacement(self, mesh: HexMesh, layers: np.ndarray | None = None) -> tuple[np.ndarray, dict]:
        extra = {} if self.cases is None else {"cases": self.cases}
        if layers is None:
            layers = build_layers(mesh, self.layer_mm)
        basis = simulate_build(mesh, self.E, self.nu, n_steps=self.n_steps, layers=layers, **extra)
        keep = None
        if self.attached is not None:
            keep = basis.plate_nodes[self.attached(mesh.nodes[basis.plate_nodes])]
        rel = release(basis, keep_fixed_nodes=keep)
        if rel.node_ids.size != mesh.n_nodes:
            raise ValueError("compensation expects the cut not to remove material")
        u = rel.combine(self.eps_xy, self.eps_z)
        info = {"plate_nodes": basis.plate_nodes, "stress": basis.stress(self.eps_xy, self.eps_z)}
        return u, info


def best_fit_rigid(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """Kabsch: rigidly move ``src`` onto ``dst`` (least squares), return moved src."""
    cs, cd = src.mean(axis=0), dst.mean(axis=0)
    H = (src - cs).T @ (dst - cd)
    U, _, Vt = np.linalg.svd(H)
    d = np.sign(np.linalg.det(Vt.T @ U.T))
    R = Vt.T @ np.diag([1, 1, d]) @ U.T
    return (src - cs) @ R.T + cd


@dataclass
class CompensationResult:
    nominal: HexMesh
    compensated: HexMesh  # mesh to print
    offset: np.ndarray  # (N, 3) compensated - nominal node coordinates
    history: list[dict] = field(default_factory=list)
    u_uncompensated: np.ndarray | None = None
    u_compensated: np.ndarray | None = None
    layer_mismatch: int = 0  # elements whose layer changes when the final shape is re-sliced
    verified: dict | None = None  # deviation after re-slicing the final shape from scratch

    @property
    def before_mm(self) -> float:
        return self.history[0]["max_deviation_mm"]

    @property
    def after_mm(self) -> float:
        return (self.verified or self.history[-1])["max_deviation_mm"]


def _deviation(x_print: np.ndarray, u: np.ndarray, x_nom: np.ndarray, align: bool) -> np.ndarray:
    final = x_print + u
    if align:
        final = best_fit_rigid(final, x_nom)
    return final - x_nom


def _min_jacobian(elems: np.ndarray, x: np.ndarray) -> float:
    from .fem import DN_GAUSS

    J = np.einsum("pnj,eni->epji", DN_GAUSS, x[elems])
    return float(np.linalg.det(J).min())


def compensate(
    mesh: HexMesh,
    model: DistortionModel,
    iterations: int = 4,
    relaxation: float = 1.0,
    tol_mm: float = 0.005,
    blend_mm: float = 3.0,
    progress=None,
) -> CompensationResult:
    """Iteratively pre-deform ``mesh`` so the printed, cut part is nominal.

    Args:
        blend_mm: height above the plate over which the vertical correction
            ramps from 0 (plate contact, printed flat) to 1. Material in this
            zone is a sacrificial/cut region and is excluded from the
            deviation metric.
    """
    x_nom = mesh.nodes.copy()
    z0 = x_nom[:, 2].min()
    ramp = np.clip((x_nom[:, 2] - z0) / max(blend_mm, 1e-9), 0.0, 1.0)
    functional = ramp >= 1.0 - 1e-9
    align = model.attached is None
    x = x_nom.copy()
    history: list[dict] = []
    u0 = None
    layers = None
    for k in range(iterations + 1):
        if k == 1:  # first pre-deformed shape: slice it horizontally, then freeze
            layers = build_layers(mesh.with_nodes(x), model.layer_mm)
        u, _ = model.final_displacement(mesh.with_nodes(x), layers=layers)
        if u0 is None:
            u0 = u
        dev = _deviation(x, u, x_nom, align)
        # The plate contact zone is cut (EDM/saw) — measure functional surfaces.
        mag = np.linalg.norm(dev[functional], axis=1)
        history.append(
            {
                "iteration": k,
                "max_deviation_mm": float(mag.max()),
                "rms_deviation_mm": float(np.sqrt((mag**2).mean())),
            }
        )
        if progress:
            progress(history[-1])
        if mag.max() < tol_mm or k == iterations:
            break
        step = relaxation * dev
        step[:, 2] *= ramp  # plate is flat: vertical correction fades out at the plate
        x_try = x - step
        while _min_jacobian(mesh.elems, x_try) <= 0.05 * mesh.pitch**3 / 8:
            step *= 0.5  # never invert an element; back off instead
            x_try = x - step
        x = x_try
    comp = mesh.with_nodes(x)
    mismatch = 0
    verified = None
    if layers is not None:
        mismatch = int((build_layers(comp, model.layer_mm) != layers).sum())
        u, _ = model.final_displacement(comp)  # independent check: re-slice, re-simulate
        mag = np.linalg.norm(_deviation(x, u, x_nom, align)[functional], axis=1)
        verified = {
            "max_deviation_mm": float(mag.max()),
            "rms_deviation_mm": float(np.sqrt((mag**2).mean())),
            "layer_mismatch_elements": mismatch,
        }
        if progress:
            progress({"verified_after_reslicing": verified})
    return CompensationResult(
        nominal=mesh,
        compensated=comp,
        offset=x - x_nom,
        history=history,
        u_uncompensated=u0,
        u_compensated=u,
        layer_mismatch=mismatch,
        verified=verified,
    )


def interpolate_nodal(mesh: HexMesh, values: np.ndarray, points: np.ndarray) -> np.ndarray:
    """Trilinear interpolation of a nodal field at arbitrary points.

    Uses the voxel lattice; corners missing from the mesh are skipped and the
    weights renormalised; points outside the solid fall back to nearest node.
    """
    shape = np.array(mesh.shape) + 1
    flat = np.ravel_multi_index(mesh.node_ijk.T, shape)
    lut = -np.ones(int(np.prod(shape)), dtype=np.int64)
    lut[flat] = np.arange(mesh.n_nodes)

    s = (points - mesh.origin) / mesh.pitch
    base = np.clip(np.floor(s).astype(np.int64), 0, shape - 2)
    t = s - base
    out = np.zeros((points.shape[0], values.shape[1]))
    wsum = np.zeros(points.shape[0])
    for di in (0, 1):
        for dj in (0, 1):
            for dk in (0, 1):
                ijk = base + [di, dj, dk]
                idx = lut[np.ravel_multi_index(ijk.T, shape)]
                w = (
                    np.where(di, t[:, 0], 1 - t[:, 0])
                    * np.where(dj, t[:, 1], 1 - t[:, 1])
                    * np.where(dk, t[:, 2], 1 - t[:, 2])
                )
                w = np.where(idx >= 0, np.clip(w, 0, None), 0.0)
                out += w[:, None] * values[np.maximum(idx, 0)]
                wsum += w
    ok = wsum > 1e-9
    out[ok] /= wsum[ok, None]
    if (~ok).any():
        _, nn = cKDTree(mesh.lattice_nodes).query(points[~ok])
        out[~ok] = values[nn]
    return out


def morph_surface(surface: trimesh.Trimesh, mesh: HexMesh, offset: np.ndarray) -> trimesh.Trimesh:
    """Apply a nodal offset field to an STL (the compensated CAD to print)."""
    new = surface.copy()
    new.vertices = surface.vertices + interpolate_nodal(mesh, offset, surface.vertices)
    return new
