# PreWarp — design

*Predict how a metal LPBF/SLM part will warp, then pre-warp the CAD so it should print true.*

## Why this exists

In laser powder-bed fusion every layer is melted and cools against a colder
solid below it. The shrinkage is constrained, residual stress builds up, and the
part distorts — during the build and again, sometimes violently, when it is cut
off the build plate. Shops either eat the scrap rate, add machining stock, or
pay for commercial simulation (Simufact Additive, Ansys Additive, Netfabb).

PreWarp is an open-source engine that does the two things that actually save
money:

1. **Predict** the distortion field of a part before printing (minutes, laptop).
2. **Compensate**: produce a pre-distorted STL that, after printing and
   springback, lands on the nominal geometry.

…and wraps both in an **LLM engineering layer** (MCP server + Claude agent) so an
engineer can say *"this bracket warps 0.4 mm at the tip, fix it"* and get a
compensated STL plus a report where every number is traceable to the solver.

## What makes it valuable (and what makes it impressive)

| Value for a shop | Portfolio signal |
|---|---|
| Compensated STL, not just a heat map | Real physics (FEM), written from scratch, vectorised |
| Validated against public NIST AM-Bench measurements | Honest numbers: calibrated vs. held-out, error bars |
| Fast: inherent-strain method, laptop-scale | Engineering judgement: the method industry actually uses |
| Natural-language front end | LLM tool use done right: MCP, grounding check, no invented numbers |

## Method

**Inherent strain method** (Ueda; Liang et al.; used by Simufact, Ansys, Netfabb).
Instead of simulating the melt pool, each deposited layer carries a calibrated
eigenstrain `ε* = (ε_xy, ε_xy, ε_z)` (in-plane isotropic because the scan
direction rotates layer to layer). A quasi-static linear-elastic problem is
solved layer by layer:

- Geometry (STL) → voxelised → 8-node hexahedral mesh. Node coordinates are
  free, so the same mesh can be morphed for compensation.
- Build simulation: layers are activated in `n` lumped steps. Each step solves
  `K_active Δu = f*_new` with the build plate as a rigid support and adds `Δu`
  to the accumulated field. Newly activated material is deposited stress-free
  on the recoated (flat) powder bed.
- Plate removal / partial cut: reaction forces at the released nodes are
  applied in reverse on the as-built structure → springback.
- **Linearity in ε\***: displacement is linear in the two inherent strains, so
  calibration is two unit simulations + linear least squares. Fast and exact.

**Compensation**: fixed-point iteration on node coordinates
`x_{k+1} = x_k − α (x_k + u(x_k) − x_nominal)`, re-solving on the morphed mesh
each iteration (geometric effect of the pre-distortion included). The STL
surface is morphed with trilinear interpolation of the final displacement field.

## Validation

NIST AM-Bench 2018 (AMB2018-01, IN625 bridge artifacts) and 2022 (AMB2022-01,
IN718) publish part-deflection measurements after legs are cut from the plate.
PreWarp:

- calibrates ε* on one artifact/dataset,
- predicts the held-out one, and
- reports error metrics honestly, without comparing against the blind challenge entries
  (they predicted from process parameters only, so it would not be like for like).

## LLM layer

- `prewarp.mcp_server` — MCP server (stdio) exposing tools: `analyze_part`,
  `compensate_part`, `rank_orientations`, `make_report`, `list_materials`.
  Works in Claude Desktop / Claude Code without an API key.
- `prewarp.agent` — standalone Claude agent (Anthropic SDK, tool use) for the
  CLI.
- **Grounding check**: every number in the agent's final answer is matched
  against values returned by tools; unmatched numbers are flagged. The LLM
  orchestrates and explains; the solver is the only source of numbers.

## Non-goals

- Not a melt-pool or thermo-mechanical transient solver.
- No support-structure generation (supports are modelled as a stiffness zone
  only if given as geometry).
- No claims of accuracy beyond what the validation shows.

## Builder's calls (made autonomously, user can override)

- Python 3.12, numpy/scipy sparse direct solver, trimesh, pyvista for renders.
- Name: PreWarp. License: MIT. Public NIST data credited as "Credit: NIST".
