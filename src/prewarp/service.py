"""High-level engineering operations — the single source of numbers.

The CLI, the MCP server and the Claude agent all call these functions. Each
returns a JSON-serialisable dict; the LLM layer may explain and orchestrate,
but every number it reports must come from one of these results (enforced by
``prewarp.grounding``).
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np

from .compensate import DistortionModel, best_fit_rigid, compensate, morph_surface
from .geometry import load_stl, mesh_from_stl, orient
from .materials import MATERIALS, get_material
from .simulate import release, simulate_build, summarize

TARGET_ELEMENTS = 40_000


def auto_pitch(volume_mm3: float, target: int = TARGET_ELEMENTS) -> float:
    """Voxel size that gives roughly ``target`` elements (laptop-friendly)."""
    p = (volume_mm3 / target) ** (1 / 3)
    return float(max(0.25, round(p * 20) / 20))


def _out_dir(output_dir: str | None, stem: str) -> Path:
    d = Path(output_dir or "prewarp_output") / f"{stem}-{time.strftime('%Y%m%d-%H%M%S')}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_materials() -> dict:
    return {
        "materials": [
            {
                **asdict(m),
                "calibration_status": "calibrated" if m.calibrated else "literature default — calibrate before trusting absolute values",
            }
            for m in MATERIALS.values()
        ]
    }


def _model_params(material: str, eps_xy: float | None, eps_z: float | None):
    mat = get_material(material)
    exy = mat.eps_xy if eps_xy is None else float(eps_xy)
    ez = mat.eps_z if eps_z is None else float(eps_z)
    warnings = []
    if eps_xy is None and not mat.calibrated:
        warnings.append(
            f"{material}: inherent strain not calibrated for your machine; absolute distortion "
            "values are indicative (pattern and relative comparisons are reliable)."
        )
    return mat, exy, ez, warnings


def analyze_part(
    stl_path: str,
    material: str = "IN718",
    pitch_mm: float | None = None,
    removal: str = "full",
    eps_xy: float | None = None,
    eps_z: float | None = None,
    n_steps: int | None = None,
    render: bool = True,
    output_dir: str | None = None,
) -> dict:
    """Predict distortion and residual stress of an STL part.

    Args:
        removal: "full" = part cut completely off the plate (deviation reported
            after best-fit alignment, like a CMM/scan check); "none" = stays on
            the plate (as-built distortion only).
    """
    t0 = time.perf_counter()
    surface = load_stl(stl_path)
    pitch = pitch_mm or auto_pitch(abs(surface.volume))
    mat, exy, ez, warnings = _model_params(material, eps_xy, eps_z)
    mesh, _ = mesh_from_stl(surface, pitch)
    basis = simulate_build(mesh, mat.E, mat.nu, n_steps=n_steps)
    u_built = basis.combine(exy, ez)
    stress = basis.stress(exy, ez)
    result = {
        "part": Path(stl_path).name,
        "material": material,
        "eps_xy": exy,
        "eps_z": ez,
        "pitch_mm": pitch,
        "elements": mesh.n_elems,
        "bounding_box_mm": [float(v) for v in (surface.bounds[1] - surface.bounds[0])],
        "on_plate": summarize(mesh, u_built, stress, mat.yield_MPa),
        "stress_validity": (
            "Residual stress is a qualitative map: against NIST diffraction data on the AM-Bench "
            "bridges the pattern correlates well, but magnitudes are overestimated (linear-elastic, "
            "deflection-calibrated model, no plasticity). Use it to see where stress concentrates, "
            "not how high it is. Distortion is the validated output."
        ),
    }
    if result["on_plate"].get("volume_fraction_above_yield", 0) > 0.01:
        warnings.append(
            f"Linear-elastic residual stress exceeds the typical {material} yield strength "
            f"({mat.yield_MPa:.0f} MPa) in {100 * result['on_plate']['volume_fraction_above_yield']:.1f}% of the "
            "volume: expect local plasticity (real stresses are capped near yield) and consider "
            "stress relief before removal; cracking risk at sharp corners."
        )
    u_final = u_built
    if removal == "full":
        rel = release(basis)
        u_rel = rel.combine(exy, ez)
        final = best_fit_rigid(mesh.nodes + u_rel, mesh.nodes)
        u_final = final - mesh.nodes
        result["after_removal_best_fit"] = summarize(mesh, u_final)
    elif removal != "none":
        raise ValueError("removal must be 'full' or 'none'")

    out = _out_dir(output_dir, Path(stl_path).stem)
    np.savez_compressed(out / "fields.npz", nodes=mesh.nodes, elems=mesh.elems, u=u_final, stress=stress)
    if render:
        from .viz import render_distortion

        img = render_distortion(
            mesh, u_final, out / "distortion.png", scale=_exaggeration(mesh, u_final),
            title=f"{Path(stl_path).name} · {material} · predicted distortion",
        )
        result["image"] = str(img)
    result["output_dir"] = str(out)
    result["warnings"] = warnings
    result["seconds"] = round(time.perf_counter() - t0, 1)
    (out / "result.json").write_text(json.dumps(result, indent=2))
    return result


def _exaggeration(mesh, u) -> float:
    span = float(np.ptp(mesh.nodes, axis=0).max())
    umax = float(np.linalg.norm(u, axis=1).max()) or 1.0
    return float(np.clip(round(0.06 * span / umax), 1, 200))


def compensate_part(
    stl_path: str,
    material: str = "IN718",
    pitch_mm: float | None = None,
    removal: str = "full",
    eps_xy: float | None = None,
    eps_z: float | None = None,
    iterations: int = 4,
    n_steps: int | None = None,
    blend_mm: float = 3.0,
    output_dir: str | None = None,
) -> dict:
    """Write a pre-deformed STL that prints (and springs back) to the nominal shape."""
    t0 = time.perf_counter()
    surface = load_stl(stl_path)
    pitch = pitch_mm or auto_pitch(abs(surface.volume))
    mat, exy, ez, warnings = _model_params(material, eps_xy, eps_z)
    mesh, _ = mesh_from_stl(surface, pitch)
    if removal not in ("full", "none"):
        raise ValueError("removal must be 'full' or 'none'")
    model = DistortionModel(mat.E, mat.nu, exy, ez, n_steps=n_steps, attached=None)
    if removal == "none":
        model.attached = lambda p: np.ones(len(p), dtype=bool)
    res = compensate(mesh, model, iterations=iterations, blend_mm=blend_mm)
    out = _out_dir(output_dir, Path(stl_path).stem)
    comp_stl = out / f"{Path(stl_path).stem}_prewarp_compensated.stl"
    morphed = morph_surface(surface, mesh, res.offset)
    morphed.export(comp_stl)
    from .viz import render_compensation

    img = render_compensation(
        mesh, res.compensated, res.u_uncompensated, res.u_compensated, out / "compensation.png",
        scale=_exaggeration(mesh, res.u_uncompensated),
    )
    result = {
        "part": Path(stl_path).name,
        "material": material,
        "eps_xy": exy,
        "pitch_mm": pitch,
        "removal": removal,
        "max_deviation_before_mm": res.before_mm,
        "max_deviation_after_mm": res.after_mm,
        "reduction_pct": 100 * (1 - res.after_mm / res.before_mm) if res.before_mm else 0.0,
        "iterations": res.history,
        "verified_after_reslicing": res.verified,
        "max_offset_applied_mm": float(np.linalg.norm(res.offset, axis=1).max()),
        "compensated_stl": str(comp_stl),
        "compensated_stl_watertight": bool(morphed.is_watertight),
        "image": str(img),
        "note": f"Deviation measured on functional surfaces above the {blend_mm} mm plate blend zone; "
        "\"after\" is the independent check (compensated shape re-sliced and re-simulated from "
        "scratch); values are model predictions — verify with a test print.",
        "warnings": warnings,
        "seconds": round(time.perf_counter() - t0, 1),
    }
    (out / "result.json").write_text(json.dumps(result, indent=2))
    return result


DEFAULT_ORIENTATIONS = [(0, 0), (90, 0), (0, 90), (45, 0), (0, 45), (180, 0)]


def rank_orientations(
    stl_path: str,
    material: str = "IN718",
    orientations: list[list[float]] | None = None,
    pitch_mm: float | None = None,
) -> dict:
    """Fast screening of build orientations (coarse mesh, single-pass).

    Ranks by predicted max deviation after removal (best-fit), and reports
    build height (time proxy) and plate contact area (support/removal cost).
    """
    t0 = time.perf_counter()
    surface = load_stl(stl_path)
    pitch = pitch_mm or max(auto_pitch(abs(surface.volume), 12_000), 0.5)
    mat, exy, ez, warnings = _model_params(material, None, None)
    rows = []
    for rx, ry in orientations or DEFAULT_ORIENTATIONS:
        part = orient(surface, rx, ry)
        try:
            mesh, _ = mesh_from_stl(part, pitch)
            # Same lumped-layer thickness (2 voxels) for every orientation: fair comparison.
            basis = simulate_build(mesh, mat.E, mat.nu, n_steps=max(1, mesh.shape[2] // 2))
        except ValueError as err:  # floating islands -> needs supports
            rows.append({"rx_deg": rx, "ry_deg": ry, "feasible_without_supports": False, "reason": str(err)})
            continue
        rel = release(basis)
        u = best_fit_rigid(mesh.nodes + rel.combine(exy, ez), mesh.nodes) - mesh.nodes
        bottom = mesh.elem_layer() == mesh.elem_layer().min()
        rows.append(
            {
                "rx_deg": rx,
                "ry_deg": ry,
                "feasible_without_supports": True,
                "max_deviation_mm": float(np.linalg.norm(u, axis=1).max()),
                "build_height_mm": float(np.ptp(part.vertices[:, 2])),
                "plate_contact_mm2": float(bottom.sum() * pitch**2),
                "p95_residual_stress_MPa": summarize(mesh, basis.combine(exy, ez), basis.stress(exy, ez))[
                    "p95_von_mises_MPa"
                ],  # linear-elastic; compare orientations, not absolute
            }
        )
    feasible = sorted((r for r in rows if r["feasible_without_supports"]), key=lambda r: r["max_deviation_mm"])
    return {
        "part": Path(stl_path).name,
        "material": material,
        "pitch_mm": pitch,
        "ranking": feasible + [r for r in rows if not r["feasible_without_supports"]],
        "best": feasible[0] if feasible else None,
        "note": "Screening on a coarse mesh: use the ranking, then run analyze_part on the winner.",
        "warnings": warnings,
        "seconds": round(time.perf_counter() - t0, 1),
    }


def nist_validation_summary() -> dict:
    """Headline results of PreWarp vs NIST AM-Bench measurements (precomputed)."""
    path = Path(__file__).resolve().parents[2] / "docs" / "results" / "validation.json"
    if not path.exists():
        return {"error": "run scripts/validate_nist.py first"}
    data = json.loads(path.read_text())
    keep = ("case", "process", "fit_all_points", "tip_only_calibration_predicting_other_10",
            "blind_transfer_from_2018", "tip_only_calibration_predicting_other_5", "eps_xy_fit",
            "eps_xy_from_tip_only", "solve_seconds")
    return {k: {kk: vv for kk, vv in v.items() if kk in keep} for k, v in data.items() if k.startswith("AMB")}
