"""Reproduce PreWarp's validation against NIST AM-Bench bridge measurements.

    uv run python scripts/validate_nist.py            # full run (~3 min)
    uv run python scripts/validate_nist.py --quick    # skip ablations

Writes docs/results/validation.json and figures in docs/img/.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from prewarp.amb import fit_eps_xy, metrics, run_case

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "docs" / "results"
IMG = ROOT / "docs" / "img"


def main(quick: bool, plot_only: bool = False) -> None:
    if plot_only:
        return plot(json.loads((RES / "validation.json").read_text()))
    RES.mkdir(parents=True, exist_ok=True)
    IMG.mkdir(parents=True, exist_ok=True)
    out: dict = {"generated": time.strftime("%Y-%m-%d %H:%M"), "pitch_mm": 0.5}

    # --- AM-Bench 2018: calibrate one parameter on the 11-point profile -------------
    r18 = run_case("AMB2018")
    m18 = r18.case.measured()["deflection_mm"].to_numpy()
    eps18 = fit_eps_xy(r18.unit[:, 0], m18)
    tip = int(np.argmax(m18))
    eps18_tip = m18[tip] / r18.unit[tip, 0]
    others = np.arange(m18.size) != tip
    out["AMB2018"] = {
        "case": r18.case.title,
        "process": r18.case.process,
        "elements": r18.basis.mesh.n_elems,
        "dof": 3 * r18.basis.mesh.n_nodes,
        "solve_seconds": round(r18.seconds, 1),
        "eps_xy_fit": eps18,
        "fit_all_points": metrics(r18.predict(eps18), m18),
        "eps_xy_from_tip_only": eps18_tip,
        "tip_only_calibration_predicting_other_10": metrics(r18.predict(eps18_tip)[others], m18[others]),
        "eps_z_sensitivity_mm_per_unit": float(np.abs(r18.unit[:, 1]).max()),
        "x_mm": r18.x.tolist(),
        "measured_mm": m18.tolist(),
        "predicted_mm": r18.predict(eps18).tolist(),
    }

    # --- AM-Bench 2022: blind transfer + one-point calibration -----------------------
    r22 = run_case("AMB2022")
    m22 = r22.case.measured()["deflection_mm"].to_numpy()
    tip22 = int(np.argmax(m22))
    eps22_tip = m22[tip22] / r22.unit[tip22, 0]
    others22 = np.arange(m22.size) != tip22
    out["AMB2022"] = {
        "case": r22.case.title,
        "process": r22.case.process,
        "elements": r22.basis.mesh.n_elems,
        "solve_seconds": round(r22.seconds, 1),
        "blind_transfer_from_2018": metrics(r22.predict(eps18), m22),
        "eps_xy_from_tip_only": eps22_tip,
        "tip_only_calibration_predicting_other_5": metrics(r22.predict(eps22_tip)[others22], m22[others22]),
        "x_mm": r22.x.tolist(),
        "measured_mm": m22.tolist(),
        "predicted_tip_calibrated_mm": r22.predict(eps22_tip).tolist(),
        "predicted_blind_mm": r22.predict(eps18).tolist(),
    }

    # --- Ablations: what each modelling choice is worth ------------------------------
    if not quick:
        abl = {}
        for label, kw in {
            "pitch 1.0 mm": dict(pitch=1.0),
            "single step (no layer-by-layer)": dict(n_steps=1),
            "6 lumped steps": dict(n_steps=6),
            "standard hex8 (no incompatible modes)": dict(incompatible=False),
        }.items():
            r = run_case("AMB2018", **kw)
            # Same calibrated eps as the reference model: shows raw model change.
            abl[label] = {
                "tip_change_pct_vs_reference": float(
                    100 * (r.predict(eps18)[tip] - r18.predict(eps18)[tip]) / r18.predict(eps18)[tip]
                ),
                "refit": metrics(r.predict(fit_eps_xy(r.unit[:, 0], m18)), m18),
                "seconds": round(r.seconds, 1),
            }
        out["ablations_AMB2018"] = abl

    (RES / "validation.json").write_text(json.dumps(out, indent=2))
    plot(out)
    print(json.dumps({k: v for k, v in out.items() if k != "generated"}, indent=1)[:3000])


def plot(out: dict) -> None:
    plt.rcParams.update({"font.size": 11, "axes.spines.top": False, "axes.spines.right": False})
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.8), constrained_layout=True)

    a = out["AMB2018"]
    ax = axes[0]
    x = np.array(a["x_mm"])
    ax.plot(x, a["measured_mm"], "o", color="#111", ms=7, label="NIST measured (CMM)", zorder=3)
    tip_only = np.array(a["predicted_mm"]) * a["eps_xy_from_tip_only"] / a["eps_xy_fit"]  # linear in eps
    ax.plot(x, tip_only, "-", color="#e8590c", lw=2.2, label="PreWarp, calibrated on tip point only")
    tipm = max(a["measured_mm"])
    f = a["tip_only_calibration_predicting_other_10"]
    ax.set_title(f"AM-Bench 2018 · IN625 bridge\n10 held-out ridges: RMS {f['rms_um']:.1f} µm (deflection up to {tipm:.3f} mm)")
    ax.set_xlabel("position along bridge x [mm]")
    ax.set_ylabel("deflection after cutting from plate [mm]")
    ax.legend(frameon=False, fontsize=9)

    b = out["AMB2022"]
    ax = axes[1]
    x = 75 - np.array(b["x_mm"])  # same orientation as 2018 panel (free end at 0)
    ax.plot(x, b["measured_mm"], "o", color="#111", ms=7, label="NIST measured (CMM)", zorder=3)
    ax.plot(x, b["predicted_tip_calibrated_mm"], "-", color="#e8590c", lw=2.2,
            label="PreWarp, calibrated on tip point only")
    ax.plot(x, b["predicted_blind_mm"], "--", color="#1c7ed6", lw=1.8,
            label="PreWarp, blind (2018 calibration, other machine)")
    t = b["tip_only_calibration_predicting_other_5"]
    ax.set_title(f"AM-Bench 2022 · IN718 bridge\n5 held-out ridges: RMS {t['rms_um']:.1f} µm")
    ax.set_xlabel("distance from free end [mm]")
    ax.legend(frameon=False, fontsize=9)
    fig.savefig(IMG / "validation_nist.png", dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--plot-only", action="store_true", help="re-plot from docs/results/validation.json")
    args = ap.parse_args()
    main(args.quick, args.plot_only)
