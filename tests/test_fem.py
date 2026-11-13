import numpy as np
import pytest

from prewarp.fem import (
    assemble_matrix,
    assemble_vector,
    element_arrays,
    element_dofs,
    elasticity_matrix,
    solve_constrained,
)
from prewarp.mesh import box_occupancy, mesh_from_voxels

E, NU = 200_000.0, 0.3


def _three_two_one(mesh):
    """Minimal constraints that remove rigid-body motion without restraint."""
    x = mesh.nodes
    o = np.flatnonzero(np.all(np.isclose(x, x.min(axis=0)), axis=1))[0]
    lo = x.min(axis=0)
    a = np.flatnonzero(np.isclose(x[:, 1], lo[1]) & np.isclose(x[:, 2], lo[2]) & np.isclose(x[:, 0], x[:, 0].max()))[0]
    b = np.flatnonzero(np.isclose(x[:, 0], lo[0]) & np.isclose(x[:, 2], lo[2]) & np.isclose(x[:, 1], x[:, 1].max()))[0]
    return np.array([3 * o, 3 * o + 1, 3 * o + 2, 3 * a + 1, 3 * a + 2, 3 * b + 2]), x[o]


@pytest.mark.parametrize("incompatible", [False, True])
def test_free_body_with_uniform_eigenstrain_is_stress_free(incompatible):
    """Patch test: a free cube with uniform ε* just changes shape, u = ε*·x."""
    mesh = mesh_from_voxels(box_occupancy((3, 2, 2), 0.5), 0.5)
    eps = np.array([-0.002, -0.002, 0.004, 0.0, 0.0, 0.0])
    Ke, fe = element_arrays(mesh.nodes, mesh.elems, elasticity_matrix(E, NU), eps, incompatible=incompatible)
    dofs = element_dofs(mesh.elems)
    n = 3 * mesh.n_nodes
    K, f = assemble_matrix(Ke, dofs, n), assemble_vector(fe, dofs, n)
    fixed, x0 = _three_two_one(mesh)
    u = solve_constrained(K, f, fixed).reshape(-1, 3)
    expected = (mesh.nodes - x0) * eps[:3]
    np.testing.assert_allclose(u, expected, atol=1e-10)


def test_cantilever_tip_deflection_matches_beam_theory():
    """Incompatible modes must not shear-lock: tip load on a slender cantilever."""
    L, b, h, pitch = 30.0, 2.0, 2.0, 0.5
    mesh = mesh_from_voxels(box_occupancy((L, b, h), pitch), pitch)
    Ke, _ = element_arrays(mesh.nodes, mesh.elems, elasticity_matrix(E, NU))
    dofs = element_dofs(mesh.elems)
    n = 3 * mesh.n_nodes
    K = assemble_matrix(Ke, dofs, n)
    x = mesh.nodes
    root = np.flatnonzero(np.isclose(x[:, 0], 0.0))
    tip = np.flatnonzero(np.isclose(x[:, 0], L))
    P = 10.0  # N
    f = np.zeros(n)
    f[3 * tip + 2] = -P / tip.size
    fixed = (3 * root[:, None] + np.arange(3)).ravel()
    u = solve_constrained(K, f, fixed).reshape(-1, 3)
    I = b * h**3 / 12
    G = E / (2 * (1 + NU))
    expected = P * L**3 / (3 * E * I) + P * L / ((5 / 6) * G * b * h)
    got = -u[tip, 2].mean()
    assert got == pytest.approx(expected, rel=0.03)


def test_displacement_is_linear_in_eigenstrain():
    mesh = mesh_from_voxels(box_occupancy((4, 1, 2), 0.5), 0.5)
    D = elasticity_matrix(E, NU)
    dofs = element_dofs(mesh.elems)
    n = 3 * mesh.n_nodes
    fixed = (3 * np.flatnonzero(np.isclose(mesh.nodes[:, 2], 0))[:, None] + np.arange(3)).ravel()
    eps = np.array([-0.003, -0.003, 0.001, 0, 0, 0])
    _, f1 = element_arrays(mesh.nodes, mesh.elems, D, eps)
    Ke, f2 = element_arrays(mesh.nodes, mesh.elems, D, 2.5 * eps)
    K = assemble_matrix(Ke, dofs, n)
    u1 = solve_constrained(K, assemble_vector(f1, dofs, n), fixed)
    u2 = solve_constrained(K, assemble_vector(f2, dofs, n), fixed)
    np.testing.assert_allclose(u2, 2.5 * u1, rtol=1e-9, atol=1e-14)
