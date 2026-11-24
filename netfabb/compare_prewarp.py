"""PreWarp vs Netfabb vs NIST on the AMB2018-01 ridge tops (deflection after the cut).

    python netfabb/compare_prewarp.py

Reads PreWarp's prediction from docs/results/validation.json and Netfabb's from the result_*.json
files next to this script; both are calibrated on the NIST tip only."""
import json
from pathlib import Path

HERE = Path(__file__).parent
val = json.loads((HERE.parent / "docs" / "results" / "validation.json").read_text())["AMB2018"]
x, nist, pw = val["x_mm"], val["measured_mm"], val["predicted_mm"]
runs = {"Netfabb 0.32 mm": "result_nom_m16cal__comp_m16cal.json", "Netfabb 0.40 mm": "result_nom_s0487__comp_s0487.json"}


def rms_um(a, b):
    return 1000 * (sum((p - q) ** 2 for p, q in zip(a, b)) / len(a)) ** 0.5


print("x (mm)          ", " ".join(f"{v:6.1f}" for v in x))
print("NIST measured   ", " ".join(f"{v:6.3f}" for v in nist))
print("PreWarp         ", " ".join(f"{v:6.3f}" for v in pw))
for name, f in runs.items():
    nf = json.loads((HERE / f).read_text())["datum_aligned"]["validation_vs_NIST"]["ridge_mm"]
    print(f"{name:16}", " ".join(f"{v:6.3f}" for v in nf))
    print(f"  PreWarp vs {name}: RMS {rms_um(pw, nf):.1f} µm, max {1000 * max(abs(p - q) for p, q in zip(pw, nf)):.1f} µm")
