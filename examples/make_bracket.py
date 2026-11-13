"""Generate the demo part: an L-bracket with a stiffening rib (mm, z = build direction)."""

from pathlib import Path

import trimesh


def box(extents, corner):
    b = trimesh.creation.box(extents=extents)
    b.apply_translation(-b.bounds[0] + corner)
    return b


parts = [
    box((60, 24, 4), (0, 0, 0)),     # base plate
    box((4, 24, 36), (0, 0, 4)),     # upright wall
    box((32, 3, 18), (4, 10.5, 4)),  # stiffening rib
]
bracket = trimesh.boolean.union(parts)
holes = [trimesh.creation.cylinder(radius=3, height=10, sections=48) for _ in range(2)]
for h, x in zip(holes, (24, 48)):
    h.apply_translation((x, 12, 2))
bracket = trimesh.boolean.difference([bracket, *holes])
out = Path(__file__).with_name("bracket.stl")
bracket.export(out)
print(out, bracket.is_watertight, round(bracket.volume, 1))
