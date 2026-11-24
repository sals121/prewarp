"""NIST AMB2018-01 ridge deflections from Netfabb results (z after EDM cut - z before)."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from nfread import read_inc  # noqa: E402

XM = np.array([0.5, 7.5, 14.5, 21.5, 28.5, 35.5, 42.5, 49.5, 56.5, 63.5, 70.5])
DM = np.array([1.276, 0.997, 0.754, 0.551, 0.387, 0.250, 0.146, 0.065, 0.012, 0.0, 0.003])
HERE = Path(__file__).parent


def matched(tag, inc_a, inc_b):
    """Nodes present in both increments (matched by coordinates): P, u_a, u_b."""
    Pa, Ua, _ = read_inc(HERE, tag, inc_a)
    Pb, Ub, _ = read_inc(HERE, tag, inc_b)
    ka = {tuple(k): i for i, k in enumerate(np.round(Pa, 4))}
    idx = np.array([ka.get(tuple(k), -1) for k in np.round(Pb, 4)])
    ok = idx >= 0
    return Pb[ok], Ua[idx[ok]], Ub[ok]


def ridge(P, du, hw=0.5):
    top = P[:, 2] > P[:, 2].max() - 1e-6
    return np.array([du[top & (np.abs(P[:, 0] - x) <= hw + 1e-9), 2].mean() for x in XM])


if __name__ == "__main__":
    tag = sys.argv[1]
    for inc in (35, 36, 37, 38):
        P, u0, u1 = matched(tag, 34, inc)
        print(inc, np.round(ridge(P, u1 - u0), 3))
    print("NIST", DM)
