"""Residual elastic strain: NIST diffraction data vs the as-built model.

Independent check of the deflection calibration. The inherent strain is fitted
on part deflection only; here the *same* calibration predicts the lattice
(elastic) strains that NIST measured by diffraction in parts still attached to
their build-plate section. Nothing is refitted for the validation numbers.

Data credit: NIST (see ``data/nist/README.md``).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .amb import DATA
from .simulate import BuildBasis

VOIGT = {"xx": 0, "yy": 1, "zz": 2}


@dataclass(frozen=True)
class StrainDataset:
    key: str
    case: str  # key in amb.CASES
    file: str
    technique: str
    columns: dict  # component -> column index in the file
    xz_cols: tuple[int, int]
    scale: float  # file value * scale = absolute strain
    gauge_mm: tuple[float, float, float]  # (x, y, z) extent of the diffraction volume
    gauge_note: str
    uncertainty: float  # absolute strain, as stated by the source
    source: str


DATASETS = {
    "AMB2022-EDD": StrainDataset(
        key="AMB2022-EDD",
        case="AMB2022",
        file="AMB2022_EDD_results_V2.txt",
        technique="synchrotron energy-dispersive X-ray diffraction (CHESS ID1A3), part B7-P3",
        columns={"xx": 3, "zz": 4},
        xz_cols=(0, 2),
        scale=1.0,
        gauge_mm=(0.25, 1.5, 0.25),
        gauge_note="assumed equal to the 2018 CHESS ID1A3 set-up (0.25 x 1.5 x 0.25 mm); "
        "the 2022 data document does not state it",
        uncertainty=1e-4,
        source="NIST mds2-2711, AMB2022_EDD_results_V2.txt (sha256 ce098ee2...); "
        "uncertainty 1e-4 from AMB2022-01-RS-PD measurement results v1.1, p.2",
    ),
    "AMB2018-EDD": StrainDataset(
        key="AMB2018-EDD",
        case="AMB2018",
        file="IN625_EDXRD_Strain_Results.txt",
        technique="synchrotron energy-dispersive X-ray diffraction (CHESS ID1A3)",
        columns={"xx": 2, "zz": 3},
        xz_cols=(0, 1),
        scale=1e-6,  # file is in microstrain
        gauge_mm=(0.25, 1.5, 0.25),
        gauge_note="0.25 x 1.5 x 0.25 mm (mds2-3052, X-ray Diffraction Residual Strain Measurements.pdf)",
        uncertainty=1e-4,
        source="NIST mds2-3052, IN625_EDXRD_Strain_Results.txt (sha256 a73629ed...); "
        "uncertainty not stated in the file, 1e-4 assumed as for 2022",
    ),
    "AMB2018-ND": StrainDataset(
        key="AMB2018-ND",
        case="AMB2018",
        file="IN625_Neutron_Strain_Results.txt",
        technique="neutron diffraction (NIST NCNR BT8)",
        columns={"yy": 2, "xx": 3, "zz": 4},
        xz_cols=(0, 1),
        scale=1.0,
        gauge_mm=(1.5, 1.5, 1.5),
        gauge_note="~1.5 mm cube (mds2-3052, Neutron Diffraction Residual Strain Measurements.pdf)",
        uncertainty=1e-4,
        source="NIST mds2-3052, IN625_Neutron_Strain_Results.txt (sha256 f59501ef...); "
        "uncertainty not stated in the file, 1e-4 assumed",
    ),
}

# Sentinel values (e.g. +-1e6 microstrain) mark failed peak fits in the EDXRD file.
_MAX_VALID = 0.02


def load(ds: StrainDataset) -> pd.DataFrame:
    raw = np.genfromtxt(DATA / ds.file, skip_header=1)
    raw = raw[~np.isnan(raw).any(axis=1)]
    df = pd.DataFrame({"x": raw[:, ds.xz_cols[0]], "z": raw[:, ds.xz_cols[1]]})
    for comp, col in ds.columns.items():
        df[comp] = raw[:, col] * ds.scale
    valid = np.all(np.abs(df[list(ds.columns)].to_numpy()) < _MAX_VALID, axis=1)
    return df[valid].reset_index(drop=True)


def _gauge_offsets(gauge: tuple[float, float, float], n: int = 5) -> np.ndarray:
    axes = [np.linspace(-g / 2, g / 2, n) if g > 0 else np.zeros(1) for g in gauge]
    return np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1).reshape(-1, 3)


@dataclass
class GaugePrediction:
    values: dict  # component -> (P,) model elastic strain averaged over the gauge
    solid_fraction: np.ndarray  # (P,) share of the gauge volume inside the CAD solid
    von_mises_max: np.ndarray  # (P,) max model von Mises stress in the gauge [MPa]


def predict_at_gauges(
    basis: BuildBasis,
    eps_xy: float,
    eps_z: float,
    df: pd.DataFrame,
    ds: StrainDataset,
    surface,
    y_mid: float,
    stress_fn=None,
) -> GaugePrediction:
    """Average the model elastic strain over each diffraction gauge volume.

    Only material contributes to a diffraction peak, so samples in powder or
    air are ignored; ``solid_fraction`` lets the caller drop gauges that are
    mostly outside the part (thin walls, edges).
    """
    mesh = basis.mesh
    strain = basis.elastic_strain(eps_xy, eps_z)
    stress = strain @ _D(basis).T if stress_fn is None else stress_fn(strain)
    vm = _von_mises(stress)

    ijk = mesh.elem_ijk
    shape = ijk.max(axis=0) + 1
    lut = -np.ones(int(np.prod(shape)), dtype=np.int64)
    lut[np.ravel_multi_index(ijk.T, shape)] = np.arange(mesh.n_elems)

    off = _gauge_offsets(ds.gauge_mm)
    centres = np.c_[df["x"].to_numpy(), np.full(len(df), y_mid), df["z"].to_numpy()]
    pts = (centres[:, None, :] + off[None]).reshape(-1, 3)
    in_cad = surface.contains(pts).reshape(len(df), -1)

    cell = np.floor((pts - mesh.origin) / mesh.pitch).astype(np.int64)
    ok = np.all((cell >= 0) & (cell < shape), axis=1)
    elem = -np.ones(len(pts), dtype=np.int64)
    elem[ok] = lut[np.ravel_multi_index(cell[ok].T, shape)]
    elem = elem.reshape(len(df), -1)
    use = in_cad & (elem >= 0)

    values = {}
    w = use.astype(float)
    n = np.maximum(w.sum(axis=1), 1.0)
    safe = np.maximum(elem, 0)
    for comp in ds.columns:
        values[comp] = (strain[safe, VOIGT[comp]] * w).sum(axis=1) / n
        values[comp][~use.any(axis=1)] = np.nan
    vm_max = np.where(use, vm[safe], 0.0).max(axis=1)
    return GaugePrediction(values, in_cad.mean(axis=1), vm_max)


def _D(basis: BuildBasis) -> np.ndarray:
    from .fem import elasticity_matrix

    return elasticity_matrix(basis.E, basis.nu)


def _von_mises(s: np.ndarray) -> np.ndarray:
    from .fem import von_mises

    return von_mises(s)


def compare(pred: np.ndarray, meas: np.ndarray) -> dict:
    """Error statistics in microstrain. ``skill`` = 1 - MSE/Var(meas): 1 is
    perfect, 0 is no better than predicting the mean measured strain, < 0 is worse."""
    ok = ~np.isnan(pred) & ~np.isnan(meas)
    p, m = pred[ok] * 1e6, meas[ok] * 1e6
    if ok.sum() < 3:
        return {"n": int(ok.sum())}
    err = p - m
    var = float(np.var(m))
    return {
        "n": int(ok.sum()),
        "rms_error_ue": float(np.sqrt(np.mean(err**2))),
        "bias_ue": float(err.mean()),
        "measured_std_ue": float(np.sqrt(var)),
        "pearson_r": float(np.corrcoef(p, m)[0, 1]),
        "slope_pred_vs_meas": float(np.polyfit(m, p, 1)[0]),
        "skill": float(1 - np.mean(err**2) / var) if var > 0 else float("nan"),
    }
