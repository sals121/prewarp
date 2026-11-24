import json, sys
d = json.load(open(sys.argv[1]))
for k in ("datum_aligned", "raw"):
    r = d[k]; v = r["validation_vs_NIST"]
    print(k, "tip", round(v["tip_mm"], 3), "heldout RMS um", round(v["heldout_rms_um"], 1), "max", round(v["heldout_max_um"], 1))
    print("  ridge", v["ridge_mm"])
    for s in ("uncompensated", "compensated_prewarp_stl"):
        print("  ", s, {a: (round(b, 4) if isinstance(b, float) else b) for a, b in r[s].items()})
    print("   reduction max %.1f %%  ridge %.1f %%" % (r["reduction_max_pct"], r["reduction_ridge_pct"]), r["max_vertex_to_element_mm"])
