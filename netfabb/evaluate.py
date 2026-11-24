"""Judge PreWarp's compensated NIST bridge with Autodesk Netfabb Local Simulation (pan2).

    python evaluate.py <nominal tag> <compensated tag>

Netfabb increments: 34 = cooled, plate unbolted; 37 = wire-EDM cut up to x = 56 mm (NIST state: block
x >= 56 still welded). NIST deflection = z(37) - z(34) on the ridge tops.
A "print" = STL vertex + Netfabb displacement interpolated at that vertex (what Netfabb's own
distort_stl does), so the voxel staircase does not enter the comparison.
Datum: rigid-body motion is removed with a best fit on the welded base (plate-top nodes under the
block, x >= 56, z = 0), as a CMM would align on the plate; raw numbers are kept too.
Deviation metrics match PreWarp's compensation_robustness.py: functional surfaces (>= 3 mm above the
plate), max / RMS of |deviation|, ridge-top residual at the NIST x positions."""
import json
import sys
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from nfread import read_inc, read_types  # noqa: E402
from ridge import DM, XM, matched, ridge  # noqa: E402

BLEND = 3.0


def incs(tag):
    """(before cut, NIST cut state) increments: the step before *SBDR starts, and *SBDR step 3."""
    lines = (HERE / f"{tag}_mechanical.console").read_text(errors="replace").splitlines()
    i = next(k for k, l in enumerate(lines) if "Substrate directional removal time increment           3" in l)
    cut = int(next(l for l in lines[i:] if l.strip().startswith("inc =")).split()[2])
    return cut - 3, cut
V0, VC = np.load(HERE / "V0.npy"), np.load(HERE / "Vc.npy")


def kabsch(A, B):
    """Rigid transform (R, t) minimising |R A + t - B|."""
    ca, cb = A.mean(0), B.mean(0)
    U, _, Vt = np.linalg.svd((A - ca).T @ (B - cb))
    d = np.sign(np.linalg.det(Vt.T @ U.T))
    R = Vt.T @ np.diag([1, 1, d]) @ U.T
    return R, cb - R @ ca


def datum_mask(P):
    return (np.abs(P[:, 2]) < 1e-6) & (P[:, 0] >= 56 - 1e-6) & (P[:, 0] <= 75 + 1e-6) \
        & (P[:, 1] >= -1e-6) & (P[:, 1] <= 5 + 1e-6)


def remove_rigid(P, U, ref_U=None):
    """Displacement with the rigid motion of the datum nodes removed (relative to ref_U if given)."""
    m = datum_mask(P)
    A = P[m] + (0 if ref_U is None else ref_U[m])
    R, t = kabsch(A, P[m] + U[m])
    base = P + (0 if ref_U is None else ref_U)
    moved = P + U
    return (moved - t) @ R - base + (0 if ref_U is None else ref_U), R, t


def interp(P, U, geo, types, X, k=40):
    """Displacement at points X from Netfabb's own finite-element field: trilinear shape functions
    of the part hexahedron (axis-aligned voxel) that contains each point; points just outside the
    voxelised part (STL staircase) use the nearest part element, extrapolated.
    Returns (u at X, largest distance from a point to its element box)."""
    C = geo[1]["cells"]["hexa8"][types == 2]
    lo, hi = P[C].min(1), P[C].max(1)
    _, cand = cKDTree((lo + hi) / 2).query(X, k)
    gap = np.linalg.norm(np.maximum(0, np.maximum(lo[cand] - X[:, None], X[:, None] - hi[cand])), axis=2)
    gap += 1e-9 * np.linalg.norm((lo[cand] + hi[cand]) / 2 - X[:, None], axis=2)  # tie-break: nearest centre
    e = cand[np.arange(len(X)), gap.argmin(1)]
    t = (X - lo[e]) / (hi[e] - lo[e])
    corners = P[C[e]]  # (n, 8, 3)
    at_hi = np.isclose(corners, hi[e][:, None, :])
    w = np.prod(np.where(at_hi, t[:, None, :], 1 - t[:, None, :]), axis=2)  # (n, 8)
    out = np.einsum("nk,nkd->nd", w, U[C[e]])
    return out, float(gap.min(1).max())


def stats(dev):
    func = V0[:, 2] >= BLEND - 1e-9
    mag = np.linalg.norm(dev[func], axis=1)
    top = np.isclose(V0[:, 2], V0[:, 2].max())
    r = np.array([dev[top & (np.abs(V0[:, 0] - x) <= 0.5 + 1e-9), 2].mean() for x in XM])
    return {"max_mm": float(mag.max()), "rms_mm": float(np.sqrt((mag ** 2).mean())),
            "ridge_max_abs_um": float(np.abs(r).max() * 1000), "ridge_um": (r * 1000).round(1).tolist()}


def validation(tag, align):
    before, cut = incs(tag)
    P, u0, u1 = matched(tag, before, cut)
    du = u1 - u0
    if align:
        du = remove_rigid(P, u1, ref_U=u0)[0] - u0
    r = ridge(P, du)
    held = np.arange(len(XM)) != int(np.argmax(DM))
    return {"ridge_mm": r.round(4).tolist(), "tip_mm": float(r[0]),
            "heldout_rms_um": float(np.sqrt(((r - DM)[held] ** 2).mean()) * 1000),
            "heldout_max_um": float(np.abs(r - DM)[held].max() * 1000)}


def judge(nom, comp, align):
    cn, cc = incs(nom)[1], incs(comp)[1]
    Pn, Un, gn = read_inc(HERE, nom, cn)
    Pc, Uc, gc = read_inc(HERE, comp, cc)
    if align:
        Un, Uc = remove_rigid(Pn, Un)[0], remove_rigid(Pc, Uc)[0]
    un, nn = interp(Pn, Un, gn, read_types(HERE, nom, cn, gn), V0)
    uc, nc = interp(Pc, Uc, gc, read_types(HERE, comp, cc, gc), VC)
    before, after = stats(un), stats(VC + uc - V0)
    return {"validation_vs_NIST": validation(nom, align), "uncompensated": before,
            "compensated_prewarp_stl": after,
            "reduction_max_pct": 100 * (1 - after["max_mm"] / before["max_mm"]),
            "reduction_ridge_pct": 100 * (1 - after["ridge_max_abs_um"] / before["ridge_max_abs_um"]),
            "max_vertex_to_element_mm": [nn, nc]}


if __name__ == "__main__":
    nom, comp = sys.argv[1], sys.argv[2]
    prm = (HERE / f"{nom}_thermal.in").read_text().split("*PBPF\n")[1].split("\n")[0].strip('"')
    res = {"solver": "Autodesk Netfabb Local Simulation 2026 (pan2 v26.0.27), thermo-mechanical part-level, *PPLA",
           "prm": prm, "nominal_tag": nom, "compensated_tag": comp,
           "datum_aligned": judge(nom, comp, True), "raw": judge(nom, comp, False)}
    print(json.dumps(res, indent=1))
    (HERE / f"result_{nom}__{comp}.json").write_text(json.dumps(res, indent=2))
