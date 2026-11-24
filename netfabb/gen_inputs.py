"""Write Netfabb (pan2) thermal + mechanical inputs for the NIST AMB2018-01 bridge.
Substrate x-range chosen so *SBDR's third cut step (75 % of the plate removed from -x)
ends at x = 56 mm: the NIST wire-EDM cut that leaves the x >= 56 block welded."""
import sys
from pathlib import Path
HERE = Path(__file__).parent
import os
MAT = (Path(r"C:/Program Files/Autodesk/Netfabb 2026/SIM/SUN/data/materials") / os.environ.get("NF_MAT", "inc625.txt")).read_text().replace("*SPECIFIC HEAT", "*SPECIFIC HEAT").strip()
XCUT, XMIN = 56.0, -5.0
XMAX = XMIN + (XCUT - XMIN) / 0.75
PBPA = int(sys.argv[2]) if len(sys.argv) > 2 else 12
PRM = sys.argv[3] if len(sys.argv) > 3 else "EOS_M290_Inc625_20um.prm"


def common(stl):
    return f"""*TITLE
PreWarp cross-check: NIST AMB2018-01 IN625 bridge
*PBDL
4
*RCTR
20, 0
*CAS1
*PBPF
"{PRM}"
*STLFILE
"{stl}"
*STLM
1 1 1 1

*SBDM
{XMIN:.6f}, {XMAX:.6f}, -5.0, 10.0
*DDM!
0, -12.7
*MNLR
3
*PBPA
{PBPA}
*PBLR
1
*ADAP
6
*TRANSIENT TIMING CONTROL
0.000000e+00, 1.000000e+300, 1.000000e-01, 5.000000e+04, 1.000000e-02, 2.500000e+04, 10, 99999
"""


def material():
    return f"""*AMBIENT TEMPERATURE
25
*PBSH
35
*FINT
25
*MATERIAL PROPERTIES
*MATID
1
*PBSN
3
*MATERIAL PROPERTIES
*MATID
3
{MAT}
"""


def write(tag, stl):
    th = common(stl) + "*ANTP\n2\n*BINARY\n*CONV\n2.5e-05, 200.000000\n" + material() + "*ENSIGHT GOLD OUTPUT\n*END\n"
    me = (common(stl) + f'*ANTP\n4\n*DEPENDENT THERMAL ANALYSIS\n"{tag}_thermal"\n*PPLA\n*FSUB\n*SBDR\n0\n*RBMO\n0, 10000, 1.0e-10, 0.01, 0.1\n*WRTU\n*OVTK\n'
          + material() + "*OWFC\n1\n*ENSIGHT GOLD OUTPUT\n*END\n")
    (HERE / f"{tag}_thermal.in").write_text(th)
    (HERE / f"{tag}_mechanical.in").write_text(me)
    (HERE / f"{tag}.que").write_text(f"{tag}_thermal\n{tag}_mechanical\n")
    print("wrote", tag, PRM, "substrate x", XMIN, XMAX, "PBPA", PBPA)


if __name__ == "__main__":
    tag = sys.argv[1]
    write(tag, {"nom": "bridge_nominal_raw.stl", "comp": "bridge_prewarp_comp.stl"}[tag.split("_")[0]])
