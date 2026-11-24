# PreWarp checked against Autodesk Netfabb

An independent check of PreWarp on the NIST AMB2018-01 IN625 bridge with a commercial
thermo-mechanical solver: Netfabb Local Simulation 2026 (solver `pan2` v26.0.27, educational
licence). Each case runs from the command line: `pan2 <case>_thermal -s`, then
`pan2 <case>_mechanical -s` (`run_scan.sh`).

Two questions:

1. **Prediction.** Calibrated the same way as PreWarp, does Netfabb predict the measured NIST bridge,
   and does it agree with PreWarp?
2. **Compensation.** Netfabb "prints" PreWarp's compensated STL (`bridge_prewarp_comp.stl`, untouched).
   How much of the distortion is left?

Everything here is simulation. No compensated part has been printed yet.

## Set-up (`gen_inputs.py`)

- Thermo-mechanical part-level analysis with post-cooling plasticity (`*PPLA`), IN625 properties from
  Netfabb's `inc625.txt`. Build plate 12.7 mm thick. `*PBDL 4`: four bridges on the NIST plate.
- Process file: Netfabb's own `EOS_M290_Inc625_20um.prm`. NIST built AMB2018-01 on an EOS M270 in IN625
  with 20 µm layers. The `.prm` files are Autodesk's and are not redistributed here. They ship with
  Netfabb in `SIM/SUN/data/parameters`. The scaled versions are made with Autodesk's tool:
  `prm_scale EOS_M290_Inc625_20um.prm EOS_M290_Inc625_20um_s0487.prm 0.487`.
- Mesh: `*PBPA 20` gives a 0.4 mm smallest element and `*PBPA 16` gives 0.32 mm. `*PBPA 12` (0.24 mm)
  crashed with an access violation while writing the mesh, so 0.32 mm is the finest mesh that ran.
- NIST wire-EDM cut: `*FSUB` + `*SBDR 0`. The substrate x-range (`*SBDM`) is chosen so that the third
  removal step ends exactly at x = 56 mm. That leaves the x ≥ 56 mm block welded to the plate, as in
  the NIST part. `evaluate.py` reads the before-cut and after-cut increments from the solver log.

## Calibration (the same rule as PreWarp)

NIST deflection = z(after cut) − z(before cut) on the ridge tops. Rigid-body motion is removed with a
best fit on the welded base: the small plate piece left by `*SBDR` rotates, while the real NIST plate
is large and stiff. Out of the box, Netfabb predicts a 1.53 mm tip against 1.276 mm measured (+20 %).
Only the tip is used to recalibrate, with `prm_scale`. The response is strongly non-linear because of
plasticity (`calibration_scan.json`):

| prm scale, 0.4 mm mesh | 0.25 | 0.30 | **0.487** | 0.50 | 0.70 | 0.916 | 1.0 |
|---|---|---|---|---|---|---|---|
| tip (mm) | 0.591 | 0.746 | **1.283** | 1.311 | 1.430 | 1.501 | 1.532 |
| RMS vs NIST on the 10 held-out points (µm) | 250 | 196 | **9.0** | 7.7 | 45 | 70 | 80 |

Netfabb is not mesh-converged at these sizes. With the same process file, the 0.32 mm mesh gives a tip
20 % larger than the 0.4 mm mesh. So each mesh is calibrated on its own: scale 0.404 at 0.32 mm,
0.487 at 0.4 mm.

## 1. Prediction: Netfabb vs PreWarp vs NIST (`compare_prewarp.py`)

| | RMS vs NIST, 10 held-out points | RMS vs PreWarp along the bridge |
|---|---|---|
| PreWarp | 9.8 µm | – |
| Netfabb, 0.32 mm mesh | 12.9 µm | 13.4 µm (max 22 µm) |
| Netfabb, 0.40 mm mesh | 9.0 µm | 7.8 µm (max 13 µm) |

A linear inherent-strain model and a thermo-mechanical model with plasticity, each calibrated on one
point, predict the same deflection curve within 8–13 µm RMS, on deflections up to 1.3 mm.

## 2. Compensation (`evaluate.py <nominal> <compensated>` → `result_*.json`)

The shape of a print is each STL vertex plus the Netfabb displacement, interpolated with Netfabb's own
hexahedral shape functions, so the voxel staircase does not enter the comparison. The metrics match
PreWarp's `scripts/compensation_robustness.py`: surfaces more than 3 mm above the plate, maximum and RMS
deviation from the CAD, and the residual on the ridge tops that NIST measured.

| mesh | max deviation: CAD printed → PreWarp STL printed | reduction | NIST ridge tops |
|---|---|---|---|
| 0.32 mm | 1.447 → 0.061 mm | **−95.8 %** | 1345 → 20 µm (−98.5 %) |
| 0.40 mm | 1.494 → 0.139 mm | **−90.7 %** | 1371 → 92 µm (−93.3 %) |

Without the datum alignment (raw Netfabb displacements) the reductions are −95.1 % (0.32 mm) and
−87.9 % (0.4 mm).

With Netfabb barely calibrated (0.4 mm mesh, prm scale 0.916, tip +18 %), the same STL removes only
−71 % (`result_nom_cal__comp_cal.json`). The compensation is only as good as the calibration, and a new
machine needs its own. `result_nom_m16__comp_m16.json` is the 0.32 mm mesh run with the 0.4 mm
calibration (tip +20 %): −86 %.

## Files

| | |
|---|---|
| `gen_inputs.py`, `run_scan.sh` | write and run the Netfabb thermal and mechanical inputs of a case |
| `nfread.py`, `ridge.py` | read Netfabb's EnSight Gold results; NIST ridge-top deflections |
| `evaluate.py`, `show.py` | judge a nominal/compensated pair; print a result file |
| `compare_prewarp.py` | PreWarp vs Netfabb vs NIST table above |
| `bridge_nominal_raw.stl`, `bridge_prewarp_comp.stl` | NIST CAD; PreWarp's compensated STL as given to Netfabb |
| `V0.npy`, `Vc.npy` | vertices of the dense nominal and compensated surfaces, same order |
| `result_*.json`, `calibration_scan.json` | results |
| `runs/` | Netfabb input decks (`.in`) and solver logs (`.console`) of every case above |

The raw Netfabb results (about 30 GB of EnSight files) are not included. `evaluate.py` expects them in
`results/` next to the logs; re-running needs a Netfabb licence.
