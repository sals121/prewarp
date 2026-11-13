"""Compensation without the "inverse crime".

Judging a compensation with the same model that produced it only proves the fixed
point converged. Here the NIST AMB2018-01 bridge is compensated with the reference
model (0.5 mm voxels, 0.5 mm activation layers, isotropic inherent strain), and the
compensated geometry is then "printed" by *different* truth models:

* shape errors, each recalibrated on the same NIST tip deflection (so every truth
  model is equally consistent with the data the reference was calibrated on):
  anisotropic inherent strain (eps_x = eps (1 +- 10 %), eps_y = eps (1 -+ 10 %)),
  coarser activation (2 or 4 voxel layers per step), and a finer mesh (0.25 mm);
* magnitude errors: the reference calibration off by +-5 %.

Residual = compensated print vs CAD on functional surfaces (> 3 mm above the plate),
plus what a CMM would see on the ridge tops (the NIST measurement points).

    uv run python scripts/compensation_robustness.py                 # all rows, resumable
    uv run python scripts/compensation_robustness.py --only "finer mesh"
    uv run python scripts/compensation_robustness.py --report-only   # JSON + figure from saved rows

Rows are saved one by one (docs/results/compensation_robustness_rows.json) and the reference
compensation is cached (prewarp_output/compensation_reference.npz), so a run that is stopped
resumes where it left off.
"""

import json
import sys
import time
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np

from prewarp.amb import CASES, DATA, ridge_probe
from prewarp.compensate import DistortionModel, compensate, interpolate_nodal
from prewarp.geometry import mesh_from_stl
from prewarp.materials import get_material
from prewarp.simulate import release, simulate_build

ROOT = Path(__file__).resolve().parents[1]
ROWS = ROOT / "docs" / "results" / "compensation_robustness_rows.json"
CACHE = ROOT / "prewarp_output" / "compensation_reference.npz"
BLEND = 3.0
case = CASES["AMB2018"]
mat = get_material(case.material)
meas = case.measured()
XM, DM = meas["x"].to_numpy(), meas["deflection_mm"].to_numpy()
TIP = int(np.argmax(DM))
X_Y_CASES = (np.array([1.0, 0, 0, 0, 0, 0]), np.array([0, 1.0, 0, 0, 0, 0]))


def attached(p):
    return p[:, 0] >= case.attached[0] - 1e-9


@dataclass
class Truth:
    name: str
    kind: str  # "reference" | "shape" | "calibration error"
    pitch: float = 0.5
    layer_mm: float | None = None
    anis: float | None = None  # eps_x = s (1 + anis), eps_y = s (1 - anis)
    scale: float = 1.0  # multiplies the reference calibration (calibration error rows)
    recalibrate: bool = False


TRUTHS = [
    Truth("reference model (inverse crime)", "reference"),
    Truth("calibration -5 %", "calibration error", scale=0.95),
    Truth("calibration +5 %", "calibration error", scale=1.05),
    Truth("anisotropic: eps_x +10 %, eps_y -10 %", "shape", anis=0.10, recalibrate=True),
    Truth("anisotropic: eps_x -10 %, eps_y +10 %", "shape", anis=-0.10, recalibrate=True),
    Truth("activation 2 voxel layers per step (1.0 mm)", "shape", layer_mm=1.0, recalibrate=True),
    Truth("activation 4 voxel layers per step (2.0 mm)", "shape", layer_mm=2.0, recalibrate=True),
    Truth("finer mesh 0.25 mm (0.5 mm activation)", "shape", pitch=0.25, layer_mm=0.5, recalibrate=True),
]


def model_for(t: Truth, s: float) -> DistortionModel:
    if t.anis is None:
        return DistortionModel(mat.E, mat.nu, s, s, n_steps=None, attached=attached, layer_mm=t.layer_mm)
    return DistortionModel(mat.E, mat.nu, s * (1 + t.anis), s * (1 - t.anis), n_steps=None,
                           attached=attached, layer_mm=t.layer_mm, cases=X_Y_CASES)


def calibrated(t: Truth, mesh) -> tuple[DistortionModel, np.ndarray, float]:
    """Truth model scaled so its predicted NIST tip deflection equals the measured one.
    Returns (model, displacement of the uncompensated print, mean eps used)."""
    m = model_for(t, mat.eps_xy * t.scale)
    if not t.recalibrate:
        u, _ = m.final_displacement(mesh)
        return m, u, mat.eps_xy * t.scale
    extra = {} if m.cases is None else {"cases": m.cases}
    basis = simulate_build(mesh, mat.E, mat.nu, n_steps=None, layer_mm=t.layer_mm, **extra)
    keep = basis.plate_nodes[attached(mesh.nodes[basis.plate_nodes])]
    rel = release(basis, keep_fixed_nodes=keep)
    w = np.array([m.eps_xy, m.eps_z])
    tip_unit = ridge_probe(rel, mesh.nodes, XM[[TIP]], half_width=max(0.5, t.pitch / 2))[0] @ w
    k = DM[TIP] / tip_unit
    m = replace(m, eps_xy=m.eps_xy * k, eps_z=m.eps_z * k)
    return m, rel.combine(m.eps_xy, m.eps_z), mat.eps_xy * t.scale * k


def peak_memory_gb() -> float | None:
    """Peak working set of this process (Windows), to document what a row needs."""
    try:
        import ctypes
        from ctypes import wintypes

        class PMC(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

        c = PMC()
        c.cb = ctypes.sizeof(PMC)
        k32, psapi = ctypes.WinDLL("kernel32"), ctypes.WinDLL("psapi")
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
        if not psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(c), c.cb):
            return None
        return round(c.PeakWorkingSetSize / 1e9, 2)
    except Exception:
        return None


def reference_compensation(mesh05):
    """Compensate once with the reference model; cached on disk."""
    if CACHE.exists():
        z = np.load(CACHE, allow_pickle=True)
        return z["offset"], z["u_compensated"], z["history"].tolist(), z["verified"].item()
    ref = model_for(TRUTHS[0], mat.eps_xy)
    res = compensate(mesh05, ref, iterations=4, tol_mm=0.001, blend_mm=BLEND,
                     progress=lambda h: print(h, flush=True))
    CACHE.parent.mkdir(exist_ok=True)
    np.savez(CACHE, offset=res.offset, u_compensated=res.u_compensated,
             history=np.array(res.history, dtype=object), verified=np.array(res.verified, dtype=object))
    return res.offset, res.u_compensated, res.history, res.verified


def ridge_residual(mesh, dev) -> np.ndarray:
    """Mean vertical deviation of the ridge-top nodes at each NIST measurement x (mm)."""
    top = np.isclose(mesh.nodes[:, 2], mesh.nodes[:, 2].max())
    hw = max(0.5, mesh.pitch / 2)
    return np.array([dev[top & (np.abs(mesh.nodes[:, 0] - x) <= hw + 1e-9), 2].mean() for x in XM])


def stats(mesh, dev) -> dict:
    func = mesh.nodes[:, 2] - mesh.nodes[:, 2].min() >= BLEND - 1e-9
    mag = np.linalg.norm(dev[func], axis=1)
    ridge = ridge_residual(mesh, dev)
    return {
        "max_mm": float(mag.max()),
        "rms_mm": float(np.sqrt((mag**2).mean())),
        "ridge_max_abs_um": float(np.abs(ridge).max() * 1000),
        "ridge_um": (ridge * 1000).round(2).tolist(),
    }


if __name__ == "__main__":
    only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else None
    saved = json.loads(ROWS.read_text()) if ROWS.exists() else {}
    t0 = time.perf_counter()
    mesh05, _ = mesh_from_stl(DATA / case.stl, 0.5)
    offset05, u_comp05, history, verified = reference_compensation(mesh05)
    print(f"reference compensation ready in {time.perf_counter() - t0:.0f} s", flush=True)

    meshes = {0.5: mesh05}
    for t in TRUTHS if "--report-only" not in sys.argv else []:
        if t.name in saved or (only and only not in t.name):
            continue
        t1 = time.perf_counter()
        if t.pitch not in meshes:
            meshes[t.pitch] = mesh_from_stl(DATA / case.stl, t.pitch)[0]
        mesh = meshes[t.pitch]
        offset = offset05 if t.pitch == 0.5 else interpolate_nodal(mesh05, offset05, mesh.nodes)
        model, u_before, eps = calibrated(t, mesh)
        x_comp = mesh.nodes + offset
        if t.kind == "reference":
            u_after = u_comp05  # the re-sliced, re-simulated check inside compensate()
        else:
            u_after, _ = model.final_displacement(mesh.with_nodes(x_comp))
        before, after = stats(mesh, u_before), stats(mesh, x_comp + u_after - mesh.nodes)
        row = {
            "truth_model": t.name,
            "kind": t.kind,
            "pitch_mm": t.pitch,
            "mean_eps_used": eps,
            "uncompensated": before,
            "compensated": after,
            "reduction_max_pct": 100 * (1 - after["max_mm"] / before["max_mm"]),
            "seconds": round(time.perf_counter() - t1, 1),
            "process_peak_memory_gb": peak_memory_gb(),
        }
        saved[t.name] = row
        ROWS.write_text(json.dumps(saved, indent=2))
        print(t.name, {k: v for k, v in after.items() if k != "ridge_um"},
              f"{row['reduction_max_pct']:.1f} %", f"peak {row['process_peak_memory_gb']} GB", flush=True)

    rows = [saved[t.name] for t in TRUTHS if t.name in saved]
    if len(rows) < len(TRUTHS):
        print(f"{len(rows)}/{len(TRUTHS)} rows done; JSON/figure not written yet")
        raise SystemExit
    res_history, res_verified = history, verified
    robust = [r for r in rows if r["kind"] != "reference"]
    worst = max(robust, key=lambda r: r["compensated"]["max_mm"])
    out = {
        "part": "NIST AMB2018-01 IN625 bridge, legs x >= 56 mm left on the plate",
        "reference_model": "0.5 mm voxels, 0.5 mm activation, isotropic eps_xy = %.5f" % mat.eps_xy,
        "compensation_iterations": res_history,
        "reference_verified_after_reslicing": res_verified,
        "truth_models": rows,
        "headline": {
            "uncompensated_max_mm": rows[0]["uncompensated"]["max_mm"],
            "worst_case_truth_model": worst["truth_model"],
            "worst_case_max_mm": worst["compensated"]["max_mm"],
            "worst_case_reduction_pct": worst["reduction_max_pct"],
            "range_max_mm": [min(r["compensated"]["max_mm"] for r in robust), worst["compensated"]["max_mm"]],
            "range_ridge_max_abs_um": [min(r["compensated"]["ridge_max_abs_um"] for r in robust),
                                       max(r["compensated"]["ridge_max_abs_um"] for r in robust)],
        },
    }
    (ROOT / "docs" / "results" / "compensation_robustness.json").write_text(json.dumps(out, indent=2))

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, (a1, a2) = plt.subplots(1, 2, figsize=(16, 5.5), layout="constrained",
                                 gridspec_kw={"width_ratios": [1.1, 1]})
    names = [r["truth_model"] for r in rows]
    mx = [r["compensated"]["max_mm"] * 1000 for r in rows]
    colors = ["#8b949e" if r["kind"] == "reference" else "#d29922" if r["kind"] == "calibration error"
              else "#1f6feb" for r in rows]
    a1.barh(names[::-1], mx[::-1], color=colors[::-1])
    for i, v in enumerate(mx[::-1]):
        a1.text(v, i, f" {v:.0f} µm", va="center", fontsize=9)
    unc = rows[0]["uncompensated"]["max_mm"] * 1000
    a1.axvline(unc, color="#cf222e", ls="--")
    a1.text(unc, len(rows) - 0.6, " uncompensated", color="#cf222e", fontsize=9, va="top")
    a1.set_xscale("log")
    a1.set_xlim(right=unc * 3)
    a1.set_xlabel("max deviation from CAD after printing the compensated STL [µm] (log)")
    a1.set_title("Same compensated STL, printed by different truth models\n"
                 "grey: same model (inverse crime) · blue: other model shape, recalibrated on NIST · "
                 "orange: calibration ±5 %", fontsize=10)
    line_colors = plt.get_cmap("tab10").colors
    for i, r in enumerate(rows):
        a2.plot(XM, r["compensated"]["ridge_um"], marker="osD^v<>p"[i % 8], ms=4,
                ls="--" if r["kind"] == "calibration error" else "-", color=line_colors[i % 10],
                label=r["truth_model"])
    a2.plot(XM, np.array(rows[0]["uncompensated"]["ridge_um"]) / 10, "k:", label="uncompensated ÷ 10")
    a2.axhline(0, color="k", lw=0.6)
    a2.set_xlabel("ridge x [mm] (NIST CMM points)")
    a2.set_ylabel("ridge-top height error [µm]")
    a2.set_title("What a CMM would measure on the compensated part")
    a2.legend(fontsize=7)
    fig.savefig(ROOT / "docs" / "img" / "compensation_robustness.png", dpi=110)
    print(json.dumps(out["headline"], indent=2))
