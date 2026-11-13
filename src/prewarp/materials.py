"""Room-temperature elastic properties of common LPBF alloys.

Inherent strains are process-dependent and must be calibrated (see
``prewarp.calibrate``); the defaults below are typical orders of magnitude
from the literature, used only when no calibration is available.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Material:
    name: str
    E: float  # MPa
    nu: float
    # Default inherent strain (in-plane, build-direction). Calibrate for real use.
    eps_xy: float = -0.004
    eps_z: float = -0.004
    calibrated: bool = False
    note: str = ""
    yield_MPa: float = 0.0  # typical as-built LPBF 0.2% yield strength (indicative)


MATERIALS: dict[str, Material] = {
    "IN625": Material(
        "IN625", 205_000.0, 0.308, eps_xy=-0.00374, eps_z=-0.00374, calibrated=True,
        note="Calibrated on NIST AMB2018-01 (EOS M270-class, 195 W, 20 µm layers); 0.5 mm activation layers",
        yield_MPa=650.0,
    ),
    "IN718": Material(
        "IN718", 200_000.0, 0.294, eps_xy=-0.00529, eps_z=-0.00529, calibrated=True,
        note="Calibrated on NIST AMB2022-01 tip deflection (AMMT, 285 W, 40 µm layers); 0.5 mm activation layers",
        yield_MPa=800.0,
    ),
    "Ti6Al4V": Material("Ti6Al4V", 113_800.0, 0.342, note="Titanium alloy", yield_MPa=1000.0),
    "316L": Material("316L", 193_000.0, 0.30, note="Austenitic stainless steel", yield_MPa=450.0),
    "AlSi10Mg": Material("AlSi10Mg", 70_000.0, 0.33, note="Aluminium alloy", yield_MPa=250.0),
}


def get_material(name: str) -> Material:
    try:
        return MATERIALS[name]
    except KeyError:
        raise KeyError(f"unknown material {name!r}; known: {', '.join(MATERIALS)}") from None
