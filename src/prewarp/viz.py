"""Renders for reports, the README and social posts (pyvista, off-screen)."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .mesh import HexMesh

BG = "#0d1117"
FG = "#e6edf3"
CMAP = "turbo"


def _pv():
    import pyvista as pv

    pv.OFF_SCREEN = True
    return pv


def to_grid(mesh: HexMesh, nodes: np.ndarray | None = None, elems_mask: np.ndarray | None = None):
    pv = _pv()
    pts = mesh.nodes if nodes is None else nodes
    elems = mesh.elems if elems_mask is None else mesh.elems[elems_mask]
    cells = np.hstack([np.full((elems.shape[0], 1), 8), elems]).ravel()
    types = np.full(elems.shape[0], pv.CellType.HEXAHEDRON, dtype=np.uint8)
    return pv.UnstructuredGrid(cells, types, pts)


def _plotter(size=(1600, 900)):
    pv = _pv()
    p = pv.Plotter(off_screen=True, window_size=size)
    p.set_background(BG)
    p.enable_anti_aliasing("ssaa")
    return p


def _bar(title, fmt="%.2f"):
    return dict(
        title=title,
        color=FG,
        title_font_size=22,
        label_font_size=18,
        fmt=fmt,
        n_labels=4,
        vertical=False,
        position_x=0.25,
        position_y=0.06,
        width=0.5,
        height=0.06,
    )


def _camera(p, mesh: HexMesh, zoom: float = 1.0):
    """Front three-quarter view: shows the bending of long parts clearly."""
    span = np.ptp(mesh.nodes, axis=0)
    p.view_xz(negative=False)
    p.camera.elevation = 22
    p.camera.azimuth = -28 if span[0] >= span[1] else 28
    p.reset_camera()
    p.camera.zoom(1.35 * zoom)


def render_distortion(
    mesh: HexMesh,
    u: np.ndarray,
    path: str | Path,
    scale: float = 10.0,
    title: str = "",
    node_ids: np.ndarray | None = None,
    clim=None,
) -> Path:
    """Deformed shape (exaggerated ``scale``×) coloured by |u| in mm, with
    the nominal geometry as a ghost wireframe."""
    if node_ids is not None:  # results defined on a subset of nodes
        full = np.zeros_like(mesh.nodes)
        full[node_ids] = u
        u = full
    mag = np.linalg.norm(u, axis=1)
    grid = to_grid(mesh, mesh.nodes + scale * u)
    grid.point_data["|u| [mm]"] = mag
    ghost = to_grid(mesh).extract_feature_edges(feature_angle=30)
    p = _plotter()
    p.add_mesh(ghost, color="#8b949e", line_width=1, opacity=0.6)
    p.add_mesh(
        grid.extract_surface(algorithm="dataset_surface"),
        scalars="|u| [mm]",
        cmap=CMAP,
        clim=clim,
        smooth_shading=False,
        scalar_bar_args=_bar("displacement [mm]"),
    )
    if title:
        p.add_text(title, position="upper_left", font_size=16, color=FG)
    p.add_text(f"shape exaggerated {scale:g}x", position="upper_right", font_size=11, color="#8b949e")
    _camera(p, mesh)
    path = Path(path)
    p.screenshot(str(path))
    p.close()
    return path


def render_compensation(nominal: HexMesh, compensated: HexMesh, u_before, u_after, path, scale=10.0) -> Path:
    """Side by side: uncompensated print vs compensated print, deviation-coloured."""
    pv = _pv()
    p = pv.Plotter(off_screen=True, window_size=(1800, 1000), shape=(2, 1))
    clim = [0, float(np.linalg.norm(u_before, axis=1).max())]
    rows = [
        ("Printed as designed: distortion vs CAD", nominal.nodes, u_before),
        ("Printed from the PreWarp-compensated STL: residual vs CAD", compensated.nodes, (compensated.nodes + u_after) - nominal.nodes),
    ]
    for i, (label, x_print, dev) in enumerate(rows):
        p.subplot(i, 0)
        p.set_background(BG)
        final = x_print + u_before if i == 0 else nominal.nodes + dev
        grid = to_grid(nominal, nominal.nodes + scale * (final - nominal.nodes))
        grid.point_data["deviation [mm]"] = np.linalg.norm(final - nominal.nodes, axis=1)
        p.add_mesh(to_grid(nominal).extract_feature_edges(30), color="#8b949e", opacity=0.5)
        p.add_mesh(
            grid.extract_surface(algorithm="dataset_surface"),
            scalars="deviation [mm]",
            cmap=CMAP,
            clim=clim,
            show_scalar_bar=i == 1,
            scalar_bar_args=_bar("deviation from CAD [mm]"),
        )
        p.add_text(label, position="upper_left", font_size=14, color=FG)
        if i == 1:
            p.add_text("remaining colour = leg stubs at the plate (cut zone, not compensated)",
                       position="lower_left", font_size=10, color="#8b949e")
        _camera(p, nominal, zoom=1.5)
    p.add_text(f"shape exaggerated {scale:g}x", position="upper_right", font_size=11, color="#8b949e")
    path = Path(path)
    p.screenshot(str(path))
    p.close()
    return path


def build_animation(basis, weights, path, scale=10.0, fps=8, final_u=None, node_ids=None, yield_MPa=None) -> Path:
    """GIF: the part grows layer by layer coloured by residual stress (von Mises),
    then is cut from the plate and springs back, coloured by displacement."""
    from .fem import DN_CENTER, _b_matrices, elasticity_matrix, von_mises
    from .simulate import UNIT_CASES

    mesh = basis.mesh
    w = np.asarray(weights, dtype=float)
    D = elasticity_matrix(basis.E, basis.nu)
    B = _b_matrices(mesh.nodes[mesh.elems], DN_CENTER)[0][:, 0]
    eps_star = UNIT_CASES[0] * w[0] + UNIT_CASES[1] * w[1]
    u_act = basis.u_act @ w  # (E, 24)

    def vm_at(u_nodes):
        strain = np.einsum("eij,ej->ei", B, u_nodes[mesh.elems].reshape(-1, 24) - u_act)
        return von_mises((strain - eps_star) @ D.T)

    p = _plotter((1200, 700))
    p.open_gif(str(path), fps=fps)
    ghost = to_grid(mesh).extract_feature_edges(30)
    s_final = vm_at(basis.history[-1][1] @ w)
    s_lim = [0.0, float(yield_MPa or np.percentile(s_final, 98))]
    s_bar = (f"von Mises [MPa], red = at yield ({yield_MPa:.0f} MPa)" if yield_MPa
             else "residual stress, von Mises [MPa]")

    def frame(mask, u, cell_vals=None, point_vals=None, clim=None, bar="", label=""):
        p.clear()
        p.add_mesh(ghost, color="#8b949e", opacity=0.4)
        g = to_grid(mesh, mesh.nodes + scale * u, mask)
        if cell_vals is not None:
            g.cell_data["v"] = cell_vals[mask]
        else:
            g.point_data["v"] = point_vals
        p.add_mesh(g.extract_surface(algorithm="dataset_surface"), scalars="v", cmap=CMAP, clim=clim,
                   scalar_bar_args=_bar(bar, "%.0f" if "MPa" in bar else "%.2f"))
        p.add_text(f"PreWarp · {label}", position="upper_left", font_size=14, color=FG)
        _camera(p, mesh)
        p.write_frame()

    n = len(basis.history)
    u_last = basis.history[-1][1] @ w
    b_max = float(np.linalg.norm(u_last, axis=1).max())
    b_bar = f"displacement on the plate [mm] (max {b_max:.3f})"
    for k, (mask, u) in enumerate(basis.history):
        uw = u @ w
        frame(mask, uw, point_vals=np.linalg.norm(uw, axis=1), clim=[0, b_max], bar=b_bar,
              label=f"printing layer group {k + 1}/{n} · welded to the plate, distortion is held back")
    for _ in range(4):
        frame(basis.history[-1][0], u_last, point_vals=np.linalg.norm(u_last, axis=1), clim=[0, b_max],
              bar=b_bar, label="as built: residual stress locked in")
    if final_u is not None:
        full = np.zeros_like(mesh.nodes)
        full[node_ids if node_ids is not None else slice(None)] = final_u
        u0 = basis.history[-1][1] @ w
        vmax = float(np.linalg.norm(full, axis=1).max())
        for t in list(np.linspace(0, 1, 10)) + [1.0] * 8:
            ut = u0 + t * (full - u0)
            frame(basis.history[-1][0], ut, point_vals=np.linalg.norm(ut, axis=1), clim=[0, vmax],
                  bar="displacement after cutting [mm]", label="legs cut from the plate · springback")
    p.close()
    return Path(path)
