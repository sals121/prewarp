"""Mesh convergence of the calibrated deflection prediction (NIST bridges).

Two studies, both recalibrating eps_xy at every resolution:

A. fixed 2 mm activation layers, voxel pitch 2.0 / 1.0 / 0.5 / 0.25 mm:
   pure spatial discretisation error (the physics model is held fixed).
B. activation layer = voxel pitch (the production setting): the inherent strain
   is an effective parameter tied to the activation thickness, so the calibrated
   value is expected to move; what must converge is the calibrated *prediction*.

    uv run python scripts/mesh_convergence.py            # ~1 h on a 24-thread PC
    uv run python scripts/mesh_convergence.py --plot-only
    uv run python scripts/mesh_convergence.py --case AMB2022 --study A   # one block, resumable

Writes docs/results/mesh_convergence.json (incrementally) and docs/img/mesh_convergence.png.
"""

import json
import sys
import time
from pathlib import Path

import numpy as np

from prewarp.amb import CASES, DATA, fit_eps_xy, ridge_probe
from prewarp.geometry import mesh_from_stl
from prewarp.materials import get_material
from prewarp.simulate import release, simulate_build

sys.path.insert(0, str(Path(__file__).resolve().parent))
from compensation_robustness import peak_memory_gb  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "results" / "mesh_convergence.json"
PITCHES = [2.0, 1.0, 0.5, 0.25]
STUDIES = {"A_fixed_2mm_layers": lambda p: 2.0, "B_layer_equals_pitch": lambda p: p}


def run(key: str, pitch: float, layer_mm: float) -> dict:
    case = CASES[key]
    mat = get_material(case.material)
    t = time.perf_counter()
    mesh, _ = mesh_from_stl(DATA / case.stl, pitch)
    basis = simulate_build(mesh, mat.E, mat.nu, n_steps=None, layer_mm=layer_mm)
    px = mesh.nodes[basis.plate_nodes, 0]
    lo, hi = case.attached
    rel = release(basis, keep_fixed_nodes=basis.plate_nodes[(px >= lo - 1e-9) & (px <= hi + 1e-9)])
    meas = case.measured()
    x, d = meas["x"].to_numpy(), meas["deflection_mm"].to_numpy()
    unit = ridge_probe(rel, mesh.nodes, x, half_width=max(0.5, pitch / 2))[:, 0]
    tip = int(np.argmax(d))
    others = np.arange(len(d)) != tip
    eps_tip = float(d[tip] / unit[tip])
    eps_all = fit_eps_xy(unit, d)
    pred = unit * eps_tip
    return {
        "pitch_mm": pitch,
        "layer_mm": layer_mm,
        "elements": int(mesh.n_elems),
        "dof": int(3 * mesh.n_nodes),
        "activation_steps": int(basis.n_steps),
        "seconds": round(time.perf_counter() - t, 1),
        "unit_tip_response_mm": float(unit[tip]),
        "eps_xy_tip_calibrated": eps_tip,
        "eps_xy_fit_all": eps_all,
        "x_mm": x.tolist(),
        "measured_mm": d.tolist(),
        "predicted_tip_calibrated_mm": pred.tolist(),
        "heldout_rms_um": float(np.sqrt(np.mean((pred[others] - d[others]) ** 2)) * 1000),
        "heldout_max_um": float(np.abs(pred[others] - d[others]).max() * 1000),
        "fit_all_rms_um": float(np.sqrt(np.mean((unit * eps_all - d) ** 2)) * 1000),
        "process_peak_memory_gb": peak_memory_gb(),
    }


def plot(res: dict) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 3, figsize=(16, 8.5), layout="constrained")
    for r, key in enumerate(CASES):
        ax = axes[r, 0]
        for study, style in zip(STUDIES, ("o-", "s--")):
            rows = [v for v in res.get(key, {}).get(study, []) if "eps_xy_tip_calibrated" in v]
            if rows:
                ax.plot([v["pitch_mm"] for v in rows], [-v["eps_xy_tip_calibrated"] * 1e3 for v in rows],
                        style, label=study.replace("_", " "))
        ax.set_xscale("log", base=2)
        ax.invert_xaxis()
        ax.set_xlabel("voxel pitch [mm]")
        ax.set_ylabel("calibrated −ε* [10⁻³]")
        ax.set_title(f"{key}: calibrated inherent strain")
        ax.legend(fontsize=8)
        for c, study in enumerate(STUDIES, start=1):
            ax = axes[r, c]
            rows = [v for v in res.get(key, {}).get(study, []) if "x_mm" in v]
            for v in rows:
                ax.plot(v["x_mm"], v["predicted_tip_calibrated_mm"], ".-",
                        label=f"{v['pitch_mm']:g} mm: held-out RMS {v['heldout_rms_um']:.1f} µm")
            if rows:
                ax.plot(rows[0]["x_mm"], rows[0]["measured_mm"], "k*", ms=10, label="NIST measured")
            ax.set_xlabel("x [mm]")
            ax.set_ylabel("deflection [mm]")
            ax.set_title(f"{key} · {study.replace('_', ' ')}\n(tip-calibrated at each pitch)", fontsize=10)
            ax.legend(fontsize=7)
    fig.savefig(ROOT / "docs" / "img" / "mesh_convergence.png", dpi=110)


if __name__ == "__main__":
    res = json.loads(OUT.read_text()) if OUT.exists() else {}
    arg = lambda k: sys.argv[sys.argv.index(k) + 1] if k in sys.argv else None  # noqa: E731
    if "--plot-only" not in sys.argv:
        for key in CASES:
            if arg("--case") and key != arg("--case"):
                continue
            for study, layer in STUDIES.items():
                if arg("--study") and not study.startswith(arg("--study")):
                    continue
                done = {v["pitch_mm"] for v in res.get(key, {}).get(study, [])}
                for pitch in PITCHES:
                    if pitch in done:
                        continue
                    try:
                        row = run(key, pitch, layer(pitch))
                    except Exception as exc:  # record, keep going
                        row = {"pitch_mm": pitch, "layer_mm": layer(pitch), "error": repr(exc)}
                    res.setdefault(key, {}).setdefault(study, []).append(row)
                    res[key][study].sort(key=lambda v: -v["pitch_mm"])
                    OUT.write_text(json.dumps(res, indent=2))
                    print(key, study, {k: v for k, v in row.items() if not isinstance(v, list)}, flush=True)
    plot(res)
