# Results

Every number in the project README comes from one of these files. Each is written by a script
in `scripts/` and can be regenerated.

| File | Script | Contents |
|---|---|---|
| `validation.json` | `validate_nist.py` | Deflection vs NIST AM-Bench. **Headline accuracy**: 0.5 mm voxels, 0.5 mm activation layer, ε* calibrated on the tip point only, other points held out. |
| `mesh_convergence.json` | `mesh_convergence.py` | Same calibration protocol at voxel pitch 2.0 / 1.0 / 0.5 / 0.25 mm, two studies (below). |
| `residual_strain.json` | `validate_residual_strain.py` | Elastic strain vs NIST diffraction data, deflection calibration not refitted. |
| `compensation_bridge.json` | `make_figures.py` | Compensation iterations on the AMB2018 bridge, plus the re-sliced independent check. |
| `compensation_robustness.json`, `compensation_robustness_rows.json` | `compensation_robustness.py` | The compensated STL "printed" by seven truth models that differ from the reference. |

## Comparing `mesh_convergence.json` with the headline

Common to all rows: ε* calibrated on the tip point only, held-out RMS over the same NIST
points (10 on AMB2018, 5 on AMB2022), ridge probe half-width 0.5 mm.

| Study | Activation layer | Comparable with the headline? |
|---|---|---|
| `B_layer_equals_pitch` | = voxel pitch | **Yes.** The 0.5 mm rows *are* the headline: 9.8 µm (AMB2018) and 18.8 µm (AMB2022), same ε* to 12 digits. |
| `A_fixed_2mm_layers` | 2 mm (4 voxel layers per step at 0.5 mm) | **No.** A deliberately cruder physics model, used to isolate spatial discretisation error. AMB2022 at 0.25 mm gives 52.9 µm, which is the error of the 2 mm model, not of the headline. |

The study A error rises with refinement on AMB2022: 46.7 → 51.8 → 52.9 µm. The coarse mesh
partly cancels the 2 mm model's systematic mid-span over-prediction (+77 µm at 1 mm vs
+85 µm converged, at x = 32.5 mm). The changes shrink geometrically (RMS steps 5.1 → 1.1 µm;
no point moves more than 2.0 µm from 0.5 to 0.25 mm), which is convergence, not divergence.

Study B on AMB2018 also rises slightly: 8.7 → 9.8 → 10.4 µm. There the activation layer thins
with the mesh, so the physics changes as well. The trend extrapolates to roughly 11 µm.

The 2.0 mm rows are kept for completeness. With the legs only a few voxels thick, their unit
response is about 2× off, and their low RMS (12–13 µm) is fortuitous.

Study B on AMB2022 falls instead: 22.7 → 18.8 → 17.6 µm (0.25 mm: 234k elements, 19.2 GB
peak, 12 min). Against the 0.5 mm headlines, 0.25 mm changes the held-out RMS by +0.6 µm
(AMB2018) and −1.1 µm (AMB2022).
