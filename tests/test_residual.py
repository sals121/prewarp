import numpy as np
import pandas as pd
import trimesh

from prewarp.mesh import box_occupancy, mesh_from_voxels
from prewarp.residual import StrainDataset, compare, predict_at_gauges
from prewarp.simulate import simulate_build

E, NU = 200_000.0, 0.3


def _block():
    mesh = mesh_from_voxels(box_occupancy((10, 4, 6), 1.0), 1.0)
    surface = trimesh.creation.box(extents=(10, 4, 6))
    surface.apply_translation((5, 2, 3))
    return mesh, surface, simulate_build(mesh, E, NU, n_steps=None)


DS = StrainDataset("t", "t", "", "", {"xx": 0, "zz": 2}, (0, 1), 1.0, (0.1, 0.1, 0.1), "", 1e-4, "")


def test_gauge_average_matches_element_and_skips_air():
    mesh, surface, basis = _block()
    strain = basis.elastic_strain(-0.004, -0.004)
    c = mesh.elem_centers()
    e = int(np.argmin(np.linalg.norm(c - [4.5, 1.5, 3.5], axis=1)))
    df = pd.DataFrame({"x": [c[e, 0], 30.0], "z": [c[e, 2], 3.0]})
    g = predict_at_gauges(basis, -0.004, -0.004, df, DS, surface, y_mid=c[e, 1])
    assert np.isclose(g.values["xx"][0], strain[e, 0])
    assert np.isclose(g.values["zz"][0], strain[e, 2])
    assert np.isnan(g.values["xx"][1]) and g.solid_fraction[1] == 0.0


def test_vertical_inherent_strain_leaves_no_elastic_strain():
    """A layer deposited on a free top surface shrinks vertically without
    restraint: eps_z alone produces no elastic strain in this formulation.
    That is why neither deflection nor diffraction data can identify it."""
    _, _, basis = _block()
    assert np.abs(basis.elastic_strain(0.0, -0.004)).max() < 1e-12
    assert np.abs(basis.elastic_strain(-0.004, 0.0)).max() > 1e-4


def test_compare_statistics():
    m = np.linspace(-1e-3, 1e-3, 50)
    s = compare(m.copy(), m)
    assert s["rms_error_ue"] < 1e-9 and np.isclose(s["skill"], 1.0) and np.isclose(s["pearson_r"], 1.0)
    s = compare(m + 2e-4, m)
    assert np.isclose(s["bias_ue"], 200.0) and np.isclose(s["slope_pred_vs_meas"], 1.0)
