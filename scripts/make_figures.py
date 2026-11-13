"""Render the README / social figures from the NIST AMB2018-01 bridge.

    uv run python scripts/make_figures.py
"""

import json
import time
from pathlib import Path

import numpy as np

from prewarp.amb import CASES, DATA
from prewarp.compensate import DistortionModel, compensate, morph_surface
from prewarp.geometry import mesh_from_stl
from prewarp.materials import get_material
from prewarp.simulate import release, simulate_build
from prewarp.viz import build_animation, render_compensation, render_distortion

IMG = Path(__file__).resolve().parents[1] / "docs" / "img"
OUT = Path(__file__).resolve().parents[1] / "examples" / "output"
IMG.mkdir(parents=True, exist_ok=True)
OUT.mkdir(parents=True, exist_ok=True)

case = CASES["AMB2018"]
mat = get_material(case.material)
mesh, surface = mesh_from_stl(DATA / case.stl, 0.5)
attached = lambda p: p[:, 0] >= case.attached[0] - 1e-9  # noqa: E731

t = time.time()
basis = simulate_build(mesh, mat.E, mat.nu, n_steps=None, record=True)
keep = basis.plate_nodes[attached(mesh.nodes[basis.plate_nodes])]
rel = release(basis, keep_fixed_nodes=keep)
u_final = rel.combine(mat.eps_xy, mat.eps_z)
print(f"build+release {time.time() - t:.1f}s")

render_distortion(mesh, u_final, IMG / "bridge_distortion.png", scale=8,
                  title="NIST AM-Bench IN625 bridge · predicted distortion after cutting the legs",
                  node_ids=rel.node_ids)
build_animation(basis, [mat.eps_xy, mat.eps_z], IMG / "bridge_build.gif", scale=8,
                final_u=u_final, node_ids=rel.node_ids, yield_MPa=mat.yield_MPa)
print("renders done", time.time() - t)
import sys
if "--gif-only" in sys.argv:
    raise SystemExit

model = DistortionModel(mat.E, mat.nu, mat.eps_xy, mat.eps_z, n_steps=None, attached=attached)
res = compensate(mesh, model, iterations=4, progress=lambda h: print(h, flush=True))
render_compensation(mesh, res.compensated, res.u_uncompensated, res.u_compensated,
                    IMG / "bridge_compensation.png", scale=8)
stl = OUT / "AMB2018_bridge_prewarp_compensated.stl"
morph_surface(surface, mesh, res.offset).export(stl)
summary = {"history": res.history, "verified_after_reslicing": res.verified, "max_offset_mm": float(np.linalg.norm(res.offset, axis=1).max()),
           "compensated_stl": str(stl.name)}
(Path(__file__).resolve().parents[1] / "docs" / "results" / "compensation_bridge.json").write_text(
    json.dumps(summary, indent=2))
print(json.dumps(summary, indent=2), time.time() - t)
