import numpy as np
import pytest
import trimesh

from prewarp.compensate import DistortionModel, compensate, interpolate_nodal, morph_surface
from prewarp.geometry import mesh_from_stl
from prewarp.mesh import box_occupancy, mesh_from_voxels
from prewarp.simulate import release, simulate_build

E, NU = 200_000.0, 0.3


@pytest.fixture(scope="module")
def bar():
    mesh = mesh_from_voxels(box_occupancy((30, 4, 4), 1.0), 1.0)
    return mesh, simulate_build(mesh, E, NU, n_steps=None)


def _end_lift(mesh, rel, eps=(-0.004, -0.004)):
    """Height of the bar ends above its middle after release (bending measure)."""
    u = rel.combine(*eps)
    x = mesh.nodes[rel.node_ids]
    top = np.isclose(x[:, 2], x[:, 2].max()) & np.isclose(x[:, 1], 0)
    dz = u[top, 2][np.argsort(x[top, 0])]
    return min(dz[0], dz[-1]) - dz[len(dz) // 2]


def test_bar_released_from_plate_curls_up_at_the_ends(bar):
    """Top layers shrink last against a stiff substrate -> ends lift after removal."""
    mesh, basis = bar
    assert _end_lift(mesh, release(basis)) > 0


def test_as_built_part_is_in_equilibrium_on_plate(bar):
    """Releasing nothing must produce no springback."""
    mesh, basis = bar
    rel = release(basis, keep_fixed_nodes=basis.plate_nodes)
    assert np.abs(rel.du).max() < 1e-9


def test_layer_by_layer_differs_from_single_step(bar):
    mesh, basis = bar
    one = simulate_build(mesh, E, NU, n_steps=1)
    # Sequential activation is what creates the bending.
    assert _end_lift(mesh, release(basis)) > 3 * abs(_end_lift(mesh, release(one)))


def test_floating_island_is_rejected():
    occ = np.zeros((6, 3, 6), dtype=bool)
    occ[:, :, :2] = True
    occ[2:4, :, 4:] = True  # not connected to the lower slab
    with pytest.raises(ValueError, match="island"):
        simulate_build(mesh_from_voxels(occ, 1.0), E, NU)


def test_compensation_drives_predicted_deviation_down(bar):
    mesh, _ = bar
    model = DistortionModel(E, NU, -0.004, -0.004, n_steps=None, attached=None)
    res = compensate(mesh, model, iterations=3, blend_mm=1.0)
    assert res.after_mm < 0.1 * res.before_mm


def test_interpolation_reproduces_linear_field_and_morphs_stl():
    surface = trimesh.creation.box(extents=(10, 4, 3))
    surface.apply_translation(-surface.bounds[0])
    mesh, _ = mesh_from_stl(surface, 0.5)
    field = mesh.nodes * np.array([0.01, -0.02, 0.03])
    pts = surface.vertices
    np.testing.assert_allclose(interpolate_nodal(mesh, field, pts), pts * [0.01, -0.02, 0.03], atol=1e-9)
    morphed = morph_surface(surface, mesh, field)
    assert morphed.is_watertight


def test_activation_follows_real_height_of_morphed_mesh(bar):
    """A compensated (tilted) mesh must be printed in horizontal slices."""
    from prewarp.simulate import build_layers

    mesh, _ = bar
    np.testing.assert_array_equal(build_layers(mesh), mesh.elem_layer() - mesh.elem_layer().min())
    tilted = mesh.with_nodes(mesh.nodes + np.c_[0 * mesh.nodes[:, :2], -0.1 * mesh.nodes[:, 0]])
    tilted.nodes[:, 2] -= tilted.nodes[:, 2].min()
    layers = build_layers(tilted)
    x = tilted.elem_centers()[:, 0]
    top = mesh.elem_layer() == mesh.elem_layer().max()
    # same lattice layer, but the low end is printed several layers earlier
    assert layers[top & (x > 25)].max() < layers[top & (x < 5)].min()


def test_edge_only_patch_is_deferred():
    """A down-skin voxel sliced one layer early touches finished material only
    along an edge (it would sit on powder): it must wait for its face neighbour."""
    from prewarp.simulate import _defer_unsupported

    occ = np.zeros((2, 1, 3), dtype=bool)
    occ[0, 0, :] = True  # column
    occ[1, 0, 2] = True  # overhang, face-attached to the top of the column
    mesh = mesh_from_voxels(occ, 1.0)
    ijk = [tuple(r) for r in mesh.elem_ijk]
    col1, col2, over = ijk.index((0, 0, 1)), ijk.index((0, 0, 2)), ijk.index((1, 0, 2))
    groups = [mesh.elem_ijk[:, 2] == 0, np.isin(np.arange(mesh.n_elems), [col1, over]), np.isin(np.arange(mesh.n_elems), [col2])]
    out = _defer_unsupported(mesh, groups)
    assert not out[1][over] and out[2][over] and out[2][col2]
    # Nominal lattice slicing is always printable: nothing changes.
    nominal = [mesh.elem_ijk[:, 2] == k for k in range(3)]
    assert all((a == b).all() for a, b in zip(_defer_unsupported(mesh, nominal), nominal))


def test_anisotropic_cases_reduce_to_isotropic_and_layer_thickness_groups():
    occ = box_occupancy((12, 3, 4), 1.0)
    mesh = mesh_from_voxels(occ, 1.0)
    iso = simulate_build(mesh, E, NU, n_steps=None)
    xy = (np.array([1.0, 0, 0, 0, 0, 0]), np.array([0, 1.0, 0, 0, 0, 0]))
    ani = simulate_build(mesh, E, NU, n_steps=None, cases=xy)
    assert np.allclose(ani.combine(-0.004, -0.004), iso.combine(-0.004, 0.0), atol=1e-12)
    assert not np.allclose(ani.combine(-0.0044, -0.0036), iso.combine(-0.004, 0.0))
    # 2 mm activation layers on a 1 mm mesh: half as many steps.
    assert simulate_build(mesh, E, NU, n_steps=None, layer_mm=2.0).n_steps == iso.n_steps // 2
