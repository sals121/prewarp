"""STL import and voxelisation onto a build-plate-aligned grid."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import trimesh

from .mesh import HexMesh, mesh_from_voxels


def load_stl(path: str | Path) -> trimesh.Trimesh:
    mesh = trimesh.load_mesh(str(path), force="mesh")
    if not isinstance(mesh, trimesh.Trimesh) or mesh.faces.size == 0:
        raise ValueError(f"{path}: not a triangle mesh")
    return mesh


def voxelize(surface: trimesh.Trimesh, pitch: float) -> tuple[np.ndarray, np.ndarray]:
    """Occupancy grid whose voxel centres are tested for inside-ness.

    The grid is anchored to a multiple of ``pitch`` so features on round
    coordinates (typical CAD) align with voxel faces. The lowest occupied
    layer sits on the build plate.

    Returns:
        occupancy (nx, ny, nz) bool and origin (3,) of voxel (0,0,0)'s corner.
    """
    lo, hi = surface.bounds
    origin = np.floor(lo / pitch + 1e-6) * pitch
    n = np.maximum(1, np.ceil((hi - origin) / pitch - 1e-6).astype(int))
    axes = [origin[i] + (np.arange(n[i]) + 0.5) * pitch for i in range(3)]
    centers = np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1).reshape(-1, 3)
    if surface.is_watertight:
        inside = surface.contains(centers)
    else:  # fall back to surface voxelisation + flood fill
        vg = surface.voxelized(pitch).fill()
        inside = vg.is_filled(centers)
    occ = inside.reshape(n)
    if not occ.any():
        raise ValueError("voxelisation produced no solid voxels; pitch too coarse?")
    # Trim empty slabs so the bottom layer is the plate contact.
    nz = np.flatnonzero(occ.any(axis=(0, 1)))
    occ = occ[:, :, nz[0] : nz[-1] + 1]
    origin = origin + np.array([0, 0, nz[0] * pitch])
    return occ, origin


def mesh_from_stl(path_or_mesh, pitch: float) -> tuple[HexMesh, trimesh.Trimesh]:
    surface = path_or_mesh if isinstance(path_or_mesh, trimesh.Trimesh) else load_stl(path_or_mesh)
    occ, origin = voxelize(surface, pitch)
    return mesh_from_voxels(occ, pitch, origin), surface


def orient(surface: trimesh.Trimesh, rx_deg: float = 0.0, ry_deg: float = 0.0) -> trimesh.Trimesh:
    """Rotate a part about X then Y and drop it onto the plate (z_min = 0)."""
    m = surface.copy()
    T = trimesh.transformations.euler_matrix(np.radians(rx_deg), np.radians(ry_deg), 0.0, "sxyz")
    m.apply_transform(T)
    m.apply_translation([0, 0, -m.bounds[0][2]])
    return m
