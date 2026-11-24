"""Reader for Netfabb (pan2) EnSight Gold binary results: per-increment geometry + nodal displacement.

Layout (C binary, little-endian, 80-char strings): geometry = 5 header strings, optional 'extents' + 6
floats, then per part 'part', id, description, 'coordinates', nn, x[nn], y[nn], z[nn], element blocks
(type string, ne, connectivity). Displacement (.dis.ens) = description, then per part 'part', id,
'coordinates', ux[nn], uy[nn], uz[nn]. The mesh changes during the cut steps, so each increment is read
with its own geometry file; the pairing comes from the solver log."""
import re
from pathlib import Path

import numpy as np

NPE = {"point": 1, "bar2": 2, "bar3": 3, "tria3": 3, "tria6": 6, "quad4": 4, "quad8": 8, "tetra4": 4,
       "tetra10": 10, "pyramid5": 5, "pyramid13": 13, "penta6": 6, "penta15": 15, "hexa8": 8, "hexa20": 20}


class _Buf:
    def __init__(self, path):
        self.b, self.i = Path(path).read_bytes(), 0

    def _str(self, advance):
        v = self.b[self.i:self.i + 80].split(bytes(1))[0].decode("ascii", "replace").strip()
        if advance:
            self.i += 80
        return v

    def s(self):
        return self._str(True)

    def peek(self):
        return self._str(False)

    def ints(self, n):
        v = np.frombuffer(self.b, "<i4", n, self.i)
        self.i += 4 * n
        return v

    def floats(self, n):
        v = np.frombuffer(self.b, "<f4", n, self.i)
        self.i += 4 * n
        return v

    def done(self):
        return self.i >= len(self.b)


def read_geo(path):
    f, parts = _Buf(path), {}
    for _ in range(5):
        f.s()  # format, 2 descriptions, node id, element id
    if f.peek().startswith("extents"):
        f.s()
        f.floats(6)
    while not f.done():
        assert f.s() == "part"
        pid = int(f.ints(1)[0])
        desc = f.s()
        assert f.s() == "coordinates"
        nn = int(f.ints(1)[0])
        xyz = np.column_stack([f.floats(nn) for _ in range(3)]).astype(float)
        cells = {}
        while not f.done() and f.peek() != "part":
            et = f.s()
            ne = int(f.ints(1)[0])
            cells[et] = f.ints(ne * NPE[et]).reshape(ne, -1) - 1
        parts[pid] = {"desc": desc, "xyz": xyz, "cells": cells}
    return parts


def read_vec(path, geo):
    f, out = _Buf(path), {}
    f.s()
    while not f.done():
        assert f.s() == "part"
        pid = int(f.ints(1)[0])
        assert f.s() == "coordinates"
        nn = len(geo[pid]["xyz"])
        out[pid] = np.column_stack([f.floats(nn) for _ in range(3)]).astype(float)
    return out


def geo_for_inc(console_path):
    """Map increment -> geometry file number, from the solver log ('inc = N' then 'fmesh = ..._G.geo')."""
    m, inc = {}, None
    for line in Path(console_path).read_text(errors="replace").splitlines():
        a = re.match(r"\s*inc =\s*(\d+)", line)
        if a:
            inc = int(a.group(1))
        b = re.search(r"fmesh = .*_mechanical_(\d+)\.geo$", line.strip())
        if b and inc is not None:
            m[inc] = int(b.group(1))
    return m


def read_inc(here, tag, inc):
    """Node coordinates and displacement of increment `inc` (all parts concatenated)."""
    here = Path(here)
    g = geo_for_inc(here / f"{tag}_mechanical.console")[inc]
    geo = read_geo(here / "results" / f"{tag}_mechanical_{g}.geo")
    dis = read_vec(here / "results" / f"{tag}_mechanical00_{inc}.dis.ens", geo)
    P = np.vstack([geo[p]["xyz"] for p in sorted(geo)])
    U = np.vstack([dis[p] for p in sorted(geo)])
    return P, U, geo


def read_types(here, tag, inc, geo):
    """Per-element Structure_type (2 = part, 0 = build plate) for the single hexa8 part."""
    f = _Buf(Path(here) / "results" / f"{tag}_mechanical00_{inc}.typ.ens")
    f.s()
    assert f.s() == "part"
    f.ints(1)
    assert f.s() == "hexa8"
    return f.floats(len(geo[1]["cells"]["hexa8"])).astype(int)
