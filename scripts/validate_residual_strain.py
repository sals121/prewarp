"""Independent validation: residual elastic strain measured by NIST vs PreWarp.

The inherent strain of each alloy was calibrated on part *deflection* only
(``materials.py``). With that calibration, unchanged, this script predicts the
lattice strains NIST measured by diffraction in as-built bridges still attached
to their build-plate section, and reports the error.

    uv run python scripts/validate_residual_strain.py

Outputs ``docs/results/residual_strain.json`` and ``docs/img/residual_strain_*.png``.
"""

import json
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from prewarp.amb import CASES, DATA  # noqa: E402
from prewarp.geometry import mesh_from_stl  # noqa: E402
from prewarp.materials import get_material  # noqa: E402
from prewarp.residual import DATASETS, compare, load, predict_at_gauges  # noqa: E402
from prewarp.simulate import simulate_build  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
IMG, RES = ROOT / "docs" / "img", ROOT / "docs" / "results"
PITCH = 0.5
MIN_SOLID = 0.9  # drop gauges that are mostly powder / air (thin walls, edges)
NEAR_PLATE_MM = 2.0

out: dict = {
    "protocol": (
        "Inherent strain calibrated on part deflection only (materials.py), eps_z = eps_xy; no refit. "
        "Model state: as built, on a rigid plate (the measured parts were still attached to their "
        "build-plate section). Model elastic strain averaged over each diffraction gauge volume, "
        "material only. Gauges with < 90 % of their volume inside the CAD solid are excluded."
    ),
    "pitch_mm": PITCH,
    "datasets": {},
}
bases = {}
for ds in DATASETS.values():
    case = CASES[ds.case]
    mat = get_material(case.material)
    if ds.case not in bases:
        t = time.perf_counter()
        mesh, surface = mesh_from_stl(DATA / case.stl, PITCH)
        bases[ds.case] = (simulate_build(mesh, mat.E, mat.nu, n_steps=None), surface)
        print(f"{ds.case}: build simulated in {time.perf_counter() - t:.0f} s", flush=True)
    basis, surface = bases[ds.case]
    y_mid = float(surface.bounds[:, 1].mean())
    df = load(ds)
    g = predict_at_gauges(basis, mat.eps_xy, mat.eps_z, df, ds, surface, y_mid)
    keep = g.solid_fraction >= MIN_SOLID
    near = df["z"].to_numpy() - surface.bounds[0, 2] < NEAR_PLATE_MM
    above_yield = g.von_mises_max > mat.yield_MPa

    rec = {
        "technique": ds.technique,
        "source": ds.source,
        "gauge": ds.gauge_note,
        "material": mat.name,
        "eps_xy": mat.eps_xy,
        "eps_z": mat.eps_z,
        "points_in_file": int(len(df)),
        "points_compared": int(keep.sum()),
        "points_model_above_yield": int((keep & above_yield).sum()),
        "components": {},
    }
    for comp in ds.columns:
        meas, pred = df[comp].to_numpy(), g.values[comp]
        rec["components"][comp] = {
            "all": compare(pred[keep], meas[keep]),
            f"near_plate_z<{NEAR_PLATE_MM:g}mm": compare(pred[keep & near], meas[keep & near]),
            "away_from_plate": compare(pred[keep & ~near], meas[keep & ~near]),
            "model_below_yield": compare(pred[keep & ~above_yield], meas[keep & ~above_yield]),
        }

    # How much of the bias could a d0 error explain? A wrong stress-free lattice spacing
    # shifts every measured component by the same strain, so it can only remove the part of
    # the bias that is common to all components.
    res_all = np.concatenate([g.values[c][keep] - df[c].to_numpy()[keep] for c in ds.columns])
    common = float(np.nanmean(res_all))
    rec["d0_offset_test"] = {
        "note": "best uniform strain offset (what a d0 error would produce), removed from all "
        "components; the bias left over cannot come from d0",
        "best_common_offset_ue": common * 1e6,
        "stated_total_uncertainty_ue": ds.uncertainty * 1e6,
        "after_removing_offset": {
            c: compare(g.values[c][keep] - common, df[c].to_numpy()[keep]) for c in ds.columns
        },
    }

    # Diagnostic only (NOT validation): which eps_xy would the strain data pick on their own?
    # eps_z is not identifiable: a layer deposited on a free top surface shrinks vertically
    # without restraint, so the vertical inherent strain leaves almost no elastic strain.
    gu1 = predict_at_gauges(basis, 1.0, 0.0, df, ds, surface, y_mid)
    gu2 = predict_at_gauges(basis, 0.0, 1.0, df, ds, surface, y_mid)
    a1 = np.concatenate([gu1.values[c][keep] for c in ds.columns])
    a2 = np.concatenate([gu2.values[c][keep] for c in ds.columns])
    b = np.concatenate([df[c].to_numpy()[keep] for c in ds.columns])
    ok = ~np.isnan(a1)
    fx = float(a1[ok] @ b[ok] / (a1[ok] @ a1[ok]))
    rec["diagnostic_strain_fit"] = {
        "note": "least-squares eps_xy fitted to these strains, only to locate the model error; "
        "not used anywhere",
        "eps_xy_from_strains": fx,
        "eps_xy_from_deflection": mat.eps_xy,
        "ratio": fx / mat.eps_xy,
        "rms_error_ue_after_fit": float(np.sqrt(np.mean((a1[ok] * fx - b[ok]) ** 2)) * 1e6),
        "eps_z_sensitivity_vs_eps_xy": float(np.linalg.norm(a2[ok]) / np.linalg.norm(a1[ok])),
    }
    out["datasets"][ds.key] = rec
    print(ds.key, json.dumps(rec["components"], indent=1)[:1500], flush=True)

    # Figure: measured | predicted map per component + parity plot.
    comps = list(ds.columns)
    fig, axes = plt.subplots(len(comps), 3, figsize=(17, 3.4 * len(comps) + 0.6), layout="constrained",
                             gridspec_kw={"width_ratios": [1, 1, 0.42]}, squeeze=False)
    x, z = df["x"].to_numpy()[keep], df["z"].to_numpy()[keep]
    size = 6 if ds.gauge_mm[0] < 1 else 40
    for r, comp in enumerate(comps):
        meas, pred = df[comp].to_numpy()[keep] * 1e6, g.values[comp][keep] * 1e6
        lim = float(np.nanpercentile(np.abs(meas), 98))
        for c, (vals, title) in enumerate([(meas, "measured (NIST)"), (pred, "PreWarp, deflection calibration")]):
            ax = axes[r, c]
            sc = ax.scatter(x, z, c=vals, cmap="RdBu_r", vmin=-lim, vmax=lim, s=size, marker="s", linewidths=0)
            ax.set_aspect("equal")
            ax.set_title(f"ε{comp} {title}", fontsize=10)
            ax.set_xlabel("x [mm]")
            ax.set_ylabel("z [mm]")
        fig.colorbar(sc, ax=axes[r, 1], shrink=0.7, label="µε")
        ax = axes[r, 2]
        s = rec["components"][comp]["all"]
        ax.scatter(meas, pred, s=3, alpha=0.4, color="#1f6feb")
        ax.plot([-lim, lim], [-lim, lim], color="k", lw=0.8)
        ax.set_xlim(-1.3 * lim, 1.3 * lim)
        ax.set_ylim(-1.3 * lim, 1.3 * lim)
        ax.set_xlabel("measured [µε]")
        ax.set_ylabel("predicted [µε]")
        ax.set_title(f"ε{comp}: RMS error {s['rms_error_ue']:.0f} µε, r = {s['pearson_r']:.2f}", fontsize=10)
    fig.suptitle(f"{ds.key}: {ds.technique}", fontsize=11)
    fig.savefig(IMG / f"residual_strain_{ds.key}.png", dpi=110, bbox_inches="tight")
    plt.close(fig)

# Measurement-vs-measurement floor (2018): neutron vs EDXRD averaged over the neutron gauge.
nd, ed = load(DATASETS["AMB2018-ND"]), load(DATASETS["AMB2018-EDD"])
pairs = {"xx": [], "zz": []}
for _, row in nd.iterrows():
    sel = (np.abs(ed["x"] - row["x"]) <= 0.75) & (np.abs(ed["z"] - row["z"]) <= 0.75)
    if sel.sum() >= 4:
        for c in pairs:
            pairs[c].append((row[c], ed.loc[sel, c].mean()))
out["measurement_floor_AMB2018_neutron_vs_edxrd"] = {
    c: compare(np.array(v)[:, 0], np.array(v)[:, 1]) for c, v in pairs.items()
}
out["measurement_floor_AMB2018_neutron_vs_edxrd"]["note"] = (
    "neutron (1.5 mm gauge) vs mean of EDXRD points inside the same 1.5 mm square: how well two "
    "NIST techniques agree with each other on the same part; a model cannot be expected to beat it"
)
(RES / "residual_strain.json").write_text(json.dumps(out, indent=2))
print(json.dumps(out["measurement_floor_AMB2018_neutron_vs_edxrd"], indent=1))
