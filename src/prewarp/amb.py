"""NIST AM-Bench bridge benchmarks (AMB2018-01 IN625, AMB2022-01 IN718).

Data credit: NIST. Geometry from doi:10.18434/mds2-2607 and the AMB2018-01
description page; measured part deflections from Phan et al. 2019 (CC BY 4.0)
and Praniewicz et al. 2023. See ``data/nist/*.csv`` headers for provenance.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .geometry import mesh_from_stl
from .materials import get_material
from .simulate import BuildBasis, Release, release, simulate_build

DATA = Path(__file__).resolve().parents[2] / "data" / "nist"


@dataclass(frozen=True)
class BridgeCase:
    key: str
    title: str
    stl: str
    csv: str
    material: str
    x_col: str
    attached: tuple[float, float]  # x-range of the solid block left welded to the plate
    process: str

    def measured(self) -> pd.DataFrame:
        df = pd.read_csv(DATA / self.csv, comment="#")
        return df.rename(columns={self.x_col: "x"})[["x", "deflection_mm"]]


CASES = {
    "AMB2018": BridgeCase(
        key="AMB2018",
        title="AM-Bench 2018 · IN625 bridge (EOS M270-based CBM)",
        stl="AMB2018_01_Part.STL",
        csv="AMB2018-01_IN625_PD_measured.csv",
        material="IN625",
        x_col="x_mm",
        attached=(56.0, 75.0),
        process="195 W, 800 mm/s, 100 µm hatch, 20 µm layers, X/Y alternating scan",
    ),
    "AMB2022": BridgeCase(
        key="AMB2022",
        title="AM-Bench 2022 · IN718 bridge (NIST AMMT testbed)",
        stl="AMB2022-01-AMMT-PartCAD.STL",
        csv="AMB2022-01_IN718_PD_measured.csv",
        material="IN718",
        x_col="x_stl_mm",
        attached=(0.0, 19.0),
        process="285 W, 960 mm/s, 110 µm hatch, 40 µm layers, X/Y alternating, 14 mm stripes",
    ),
}


@dataclass
class BridgeRun:
    case: BridgeCase
    basis: BuildBasis
    rel: Release
    x: np.ndarray  # measurement x positions
    unit: np.ndarray  # (P, 2) springback dz at the probes per unit case
    seconds: float

    def predict(self, eps_xy: float, eps_z: float = 0.0) -> np.ndarray:
        return self.unit @ np.array([eps_xy, eps_z])


def ridge_probe(rel: Release, nodes: np.ndarray, x: np.ndarray, half_width: float = 0.5) -> np.ndarray:
    """Mean springback dz of the top-surface nodes of the ridge at each x."""
    pts = nodes[rel.node_ids]
    top = np.isclose(pts[:, 2], pts[:, 2].max())
    out = []
    for xm in x:
        sel = top & (np.abs(pts[:, 0] - xm) <= half_width + 1e-9)
        if not sel.any():
            raise ValueError(f"no ridge-top nodes near x={xm}")
        out.append(rel.du[sel, 2, :].mean(axis=0))
    return np.array(out)


def run_case(key: str, pitch: float = 0.5, n_steps: int | None = None, incompatible: bool = True) -> BridgeRun:
    case = CASES[key]
    mat = get_material(case.material)
    mesh, _ = mesh_from_stl(DATA / case.stl, pitch)
    t = time.perf_counter()
    basis = simulate_build(mesh, mat.E, mat.nu, n_steps=n_steps, incompatible=incompatible)
    px = mesh.nodes[basis.plate_nodes, 0]
    lo, hi = case.attached
    keep = basis.plate_nodes[(px >= lo - 1e-9) & (px <= hi + 1e-9)]
    rel = release(basis, keep_fixed_nodes=keep)
    seconds = time.perf_counter() - t
    meas = case.measured()
    unit = ridge_probe(rel, mesh.nodes, meas["x"].to_numpy())
    return BridgeRun(case, basis, rel, meas["x"].to_numpy(), unit, seconds)


def fit_eps_xy(unit_xy: np.ndarray, measured: np.ndarray) -> float:
    """One-parameter least squares (deflection is ~insensitive to eps_z)."""
    return float(unit_xy @ measured / (unit_xy @ unit_xy))


def metrics(pred: np.ndarray, meas: np.ndarray) -> dict:
    err = pred - meas
    return {
        "rms_um": float(np.sqrt((err**2).mean()) * 1000),
        "max_abs_um": float(np.abs(err).max() * 1000),
        "tip_error_pct": float(100 * (pred[np.argmax(meas)] - meas.max()) / meas.max()),
    }
