# NIST AM-Bench data

**Credit: National Institute of Standards and Technology (NIST).** These data were created by
NIST employees. They are U.S. Government works, not subject to copyright protection in the United
States (17 U.S.C. §105), and NIST grants a royalty-free right to use, copy and distribute them
elsewhere with acknowledgement. See <https://www.nist.gov/open/license>. NIST provides the data
"AS IS", without warranty. PreWarp is not endorsed by NIST.

## Files and sources

All NIST files are **unmodified copies**, downloaded on 2026-11-12. Where NIST publishes a SHA-256
checksum, the download was checked against it.

| File | Dataset | SHA-256 (NIST-published) |
|---|---|---|
| `AMB2018_01_Part.STL`, `AMB2018_01_Build.STL` | AMB2018-01 description page, <https://www.nist.gov/ambench/amb2018-01-description> | – |
| `AMB2022-01-AMMT-PartCAD.STL/.STEP`, `AMB2022-01-AMMT-PlateLayoutAssy.STL`, `mds2-2607_README.txt` | doi:[10.18434/mds2-2607](https://doi.org/10.18434/mds2-2607) | – |
| `AMB2022-01-RS-PD_measurement_results_v1.1.pdf`, `mds2-2711_README.txt` | doi:[10.18434/mds2-2711](https://doi.org/10.18434/mds2-2711) | – |
| `AMB2022_EDD_results_V2.txt` (synchrotron EDD lattice strain, IN718, part B7-P3) | doi:[10.18434/mds2-2711](https://doi.org/10.18434/mds2-2711) | `ce098ee2…e855` ✓ |
| `IN625_Neutron_Strain_Results.txt` (neutron diffraction, NCNR BT8) | doi:[10.18434/mds2-3052](https://doi.org/10.18434/mds2-3052) | `f59501ef…7eb2` ✓ |
| `IN625_EDXRD_Strain_Results.txt` (synchrotron EDXRD, CHESS ID1A3, microstrain) | doi:[10.18434/mds2-3052](https://doi.org/10.18434/mds2-3052) | `a73629ed…c6037` ✓ |
| `mds2-3052_README.txt` | doi:[10.18434/mds2-3052](https://doi.org/10.18434/mds2-3052) (file `3052_README.txt`, renamed) | – |

### Derived files (changed by this project)

As the NIST terms ask, derived files say what changed and when (2026-11-12):

| File | What was done |
|---|---|
| `AMB2018-01_IN625_PD_measured.csv` | Deflections transcribed from Phan et al. 2019, *IMMI* 8:318–334, Fig. 16 (CC BY 4.0), doi:[10.1007/s40192-019-00149-0](https://doi.org/10.1007/s40192-019-00149-0). Not a NIST raw file. |
| `AMB2022-01_IN718_PD_measured.csv` | Deflections from Praniewicz, Fox & Tarr 2023, *IMMI* 12, Table 8, doi:[10.1007/s40192-023-00310-w](https://doi.org/10.1007/s40192-023-00310-w), with one more decimal than Table 1 of `AMB2022-01-RS-PD_measurement_results_v1.1.pdf` (same values once rounded). Ridge x-positions were derived from the NIST CAD and measurement drawing (see the CSV header). |

## How to cite

- Lane, B., Levine, L., Deisenroth, D., Yeung, H., Tondare, V., Mekhontsev, S., Neira, J. (2022).
  *AM Bench 2022 3D Build Modeling Challenge Description Data (AMB2022-01)*, v1.0.0. NIST.
  <https://doi.org/10.18434/mds2-2607>
- Levine, L., Phan, T., Şeren, M. H., Praniewicz, M., D'Elia, C., Gnaupel-Herold, T., Nygren, K.,
  Ko, J. Y. P., Shanks, K., Bachus, N., Fox, J., Tarr, J., Pagan, D., Hill, M. (2022).
  *AM Bench 2022 Residual Elastic Strain, Residual Stress, and Part Deflection Measurements for
  IN718 3D Builds*, v1.0.0. NIST. <https://doi.org/10.18434/mds2-2711>
- Levine, L., Phan, T., Strantza, M., Gnaupel-Herold, T., Clausen, B., Pagan, D., Ko, J. Y. P.,
  Brown, D. (2023). *AM Bench 2018 Residual Elastic Strain Measurements of 3D Additive
  Manufacturing Builds of IN625 Artifacts Using Neutron Diffraction and Synchrotron X-ray
  Diffraction*, v1.0.0. NIST. <https://doi.org/10.18434/mds2-3052>
- Phan, T. Q. et al. (2019). Elastic residual strain and stress measurements and corresponding
  part deflections of 3D additive manufacturing builds of IN625 AM-Bench artifacts using neutron
  diffraction, synchrotron X-ray diffraction, and contour method. *IMMI* 8, 318–334.
  <https://doi.org/10.1007/s40192-019-00149-0>
