"""Hexahedral meshes built from voxel occupancy grids.

Node coordinates are stored explicitly (not implied by the grid) so a mesh can be
morphed — that is how geometric compensation is applied.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# Local node order of an 8-node hexahedron, as (di, dj, dk) offsets.
HEX_CORNERS = np.array(
    [
        [0, 0, 0],
        [1, 0, 0],
        [1, 1, 0],
        [0, 1, 0],
        [0, 0, 1],
        [1, 0, 1],
        [1, 1, 1],
        [0, 1, 1],
    ],
    dtype=np.int64,
)


@dataclass
class HexMesh:
    """An unstructured 8-node hexahedral mesh that remembers its voxel origin.

    Attributes:
        nodes: (N, 3) node coordinates in mm.
        elems: (E, 8) node indices per element (HEX_CORNERS order).
        elem_ijk: (E, 3) voxel index of each element.
        pitch: voxel edge length in mm.
        origin: (3,) coordinate of voxel (0, 0, 0)'s minimum corner.
        node_ijk: (N, 3) lattice index of each node.
    """

    nodes: np.ndarray
    elems: np.ndarray
    elem_ijk: np.ndarray
    pitch: float
    origin: np.ndarray
    node_ijk: np.ndarray
    shape: tuple[int, int, int] = field(default=(0, 0, 0))

    @property
    def n_nodes(self) -> int:
        return int(self.nodes.shape[0])

    @property
    def n_elems(self) -> int:
        return int(self.elems.shape[0])

    @property
    def lattice_nodes(self) -> np.ndarray:
        """Undeformed (nominal) node coordinates implied by the lattice."""
        return self.origin + self.node_ijk * self.pitch

    def elem_centers(self) -> np.ndarray:
        return self.nodes[self.elems].mean(axis=1)

    def elem_layer(self) -> np.ndarray:
        """Build-direction (z) voxel layer index of every element."""
        return self.elem_ijk[:, 2]

    def with_nodes(self, nodes: np.ndarray) -> "HexMesh":
        """Same topology, new node coordinates (used for compensation)."""
        return HexMesh(
            nodes=np.asarray(nodes, dtype=float).copy(),
            elems=self.elems,
            elem_ijk=self.elem_ijk,
            pitch=self.pitch,
            origin=self.origin,
            node_ijk=self.node_ijk,
            shape=self.shape,
        )

    def subset(self, keep: np.ndarray) -> tuple["HexMesh", np.ndarray]:
        """Mesh made of the elements where ``keep`` is True.

        Returns the new mesh and ``old_index`` (M,) mapping new node -> old node.
        """
        elems = self.elems[keep]
        used = np.unique(elems)
        remap = -np.ones(self.n_nodes, dtype=np.int64)
        remap[used] = np.arange(used.size)
        sub = HexMesh(
            nodes=self.nodes[used].copy(),
            elems=remap[elems],
            elem_ijk=self.elem_ijk[keep],
            pitch=self.pitch,
            origin=self.origin,
            node_ijk=self.node_ijk[used],
            shape=self.shape,
        )
        return sub, used

    def boundary_faces(self) -> np.ndarray:
        """(F, 4) node indices of exterior quad faces (outward winding)."""
        local = np.array(
            [
                [0, 3, 2, 1],  # -z
                [4, 5, 6, 7],  # +z
                [0, 1, 5, 4],  # -y
                [2, 3, 7, 6],  # +y
                [0, 4, 7, 3],  # -x
                [1, 2, 6, 5],  # +x
            ]
        )
        faces = self.elems[:, local].reshape(-1, 4)
        key = np.sort(faces, axis=1)
        _, inverse, counts = np.unique(key, axis=0, return_inverse=True, return_counts=True)
        return faces[counts[inverse.ravel()] == 1]


def mesh_from_voxels(occupancy: np.ndarray, pitch: float, origin=(0.0, 0.0, 0.0)) -> HexMesh:
    """Build a hex mesh with one element per occupied voxel.

    Args:
        occupancy: boolean array (nx, ny, nz); z is the build direction.
        pitch: voxel size in mm.
        origin: coordinate of the minimum corner of voxel (0, 0, 0).
    """
    occ = np.asarray(occupancy, dtype=bool)
    if occ.ndim != 3:
        raise ValueError("occupancy must be a 3-D boolean array")
    if not occ.any():
        raise ValueError("occupancy grid is empty")
    origin = np.asarray(origin, dtype=float)
    nx, ny, nz = occ.shape

    elem_ijk = np.argwhere(occ)  # (E, 3), sorted by i, j, k
    # Sort elements bottom-up so layers are contiguous; handy for build steps.
    order = np.lexsort((elem_ijk[:, 1], elem_ijk[:, 0], elem_ijk[:, 2]))
    elem_ijk = elem_ijk[order]

    corner_ijk = elem_ijk[:, None, :] + HEX_CORNERS[None, :, :]  # (E, 8, 3)
    flat = np.ravel_multi_index(corner_ijk.reshape(-1, 3).T, (nx + 1, ny + 1, nz + 1))
    used, inverse = np.unique(flat, return_inverse=True)
    elems = inverse.reshape(-1, 8)
    node_ijk = np.stack(np.unravel_index(used, (nx + 1, ny + 1, nz + 1)), axis=1)
    nodes = origin + node_ijk * pitch

    return HexMesh(
        nodes=nodes.astype(float),
        elems=elems.astype(np.int64),
        elem_ijk=elem_ijk.astype(np.int64),
        pitch=float(pitch),
        origin=origin,
        node_ijk=node_ijk.astype(np.int64),
        shape=(nx, ny, nz),
    )


def box_occupancy(size_mm, pitch: float) -> np.ndarray:
    """Solid box occupancy grid of the given (x, y, z) size."""
    n = [max(1, int(round(s / pitch))) for s in size_mm]
    return np.ones(n, dtype=bool)
