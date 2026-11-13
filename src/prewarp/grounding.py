"""Numeric grounding check for LLM answers.

The language model may orchestrate and explain. It may not originate numbers.
Every number in its final answer must be bound to a **quantity** and a **unit**
and match, within honest rounding, a solver output of the *same* quantity and
dimension (or a number in the user's request).

What a value-only check lets through and this one rejects:

* coincidences: "the tip warps 0.5 mm" when 0.5 is the voxel pitch, not a distortion;
* wrong conversions: "3.7 mm" when the solver said 0.0037 mm (3.7 µm), or a length
  quoted as MPa;
* invented percentages: "98 % less" when no tool reported a reduction;
* coarse rounding that hides the truth: "1 mm" for 1.394 mm, "0 mm" for 0.004 mm;
* bare numbers with neither a unit nor a named quantity.

Unit conversions inside one dimension (mm/µm, MPa/GPa, s/min, fraction/%, strain/µε)
and quoting a magnitude without its sign are accepted.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------- vocabulary

# unit token -> (dimension, factor to the base unit of that dimension)
_UNITS = {
    "nm": ("length", 1e-6), "µm": ("length", 1e-3), "μm": ("length", 1e-3), "um": ("length", 1e-3),
    "mm": ("length", 1.0), "cm": ("length", 10.0), "m": ("length", 1000.0),
    "pa": ("stress", 1e-6), "kpa": ("stress", 1e-3), "mpa": ("stress", 1.0), "gpa": ("stress", 1000.0),
    "%": ("pct", 1.0), "pct": ("pct", 1.0), "percent": ("pct", 1.0),
    "s": ("time", 1.0), "sec": ("time", 1.0), "seconds": ("time", 1.0), "second": ("time", 1.0),
    "min": ("time", 60.0), "minutes": ("time", 60.0), "minute": ("time", 60.0),
    "h": ("time", 3600.0), "hours": ("time", 3600.0), "hour": ("time", 3600.0),
    "°": ("angle", 1.0), "deg": ("angle", 1.0), "degrees": ("angle", 1.0),
    "µε": ("strain", 1e-6), "με": ("strain", 1e-6), "ue": ("strain", 1e-6), "microstrain": ("strain", 1e-6),
    "mm3": ("volume", 1.0), "mm³": ("volume", 1.0),
}

# quantity class -> (words that name it, dimensions it can carry). Order = priority
# when a JSON key mentions several (e.g. "volume_fraction_above_yield" is a fraction).
_QUANTITIES = {
    "fraction": ({"fraction", "share", "proportion"}, {"pct", "fraction"}),
    "reduction": ({"reduction", "reduced", "reduces", "less", "lower", "improvement", "decrease",
                   "decreased", "smaller"}, {"pct", "fraction"}),
    "error": ({"error", "errors", "miss", "misses", "missed", "off", "bias", "rms", "accuracy"},
              {"pct", "length", "strain"}),
    "offset": ({"offset", "pre-deformation", "predeformation", "pre-deformed", "pre-warp", "prewarp",
                "applied", "correction"}, {"length"}),
    "deviation": ({"deviation", "deviations", "distortion", "distorts", "displacement", "deflection",
                   "deflects", "warp", "warps", "warping", "warpage", "residual", "springback", "lift",
                   "lifts", "moves", "tip"}, {"length"}),
    "stress": ({"stress", "stresses", "mises", "yield", "mpa"}, {"stress"}),
    "strain": ({"strain", "eps", "epsilon", "ε", "ε*", "eps_xy", "eps_z", "shrinkage", "inherent"},
               {"strain"}),
    "size": ({"pitch", "voxel", "voxels", "resolution", "blend", "layer", "thickness", "size"}, {"length"}),
    "time": ({"time", "took", "takes", "runtime", "seconds", "duration", "solve"}, {"time"}),
    "count": ({"elements", "nodes", "dof", "iterations", "iteration", "steps", "layers", "points",
               "orientations", "parts", "tests"}, {"count"}),
    "angle": ({"orientation", "rotation", "rotated", "tilt", "tilted", "angle"}, {"angle"}),
    "volume": ({"volume"}, {"volume"}),
}
_WORD2Q = {}
for _q, (_words, _) in _QUANTITIES.items():
    for _w in _words:
        _WORD2Q.setdefault(_w, _q)
# Dimension a unit-less source takes from its quantity (user: "use pitch 0.5" means mm).
_DEFAULT_DIM = {"deviation": "length", "offset": "length", "size": "length", "stress": "stress",
                "strain": "strain", "reduction": "pct", "time": "time", "count": "count",
                "angle": "angle", "volume": "volume", "fraction": "fraction"}

# Ordinals ("99th") and "3D" are words, not quantities.
_NUM = re.compile(r"(?<![\w.])[-−]?\d+(?:[.,]\d+)?(?:[eE][-+]?\d+)?(?!\d)(?!(?:st|nd|rd|th|D)\b)")
_UNIT_AFTER = re.compile(
    r"\s?(mm³|mm3|µm|μm|um|nm|cm|mm|m(?![a-zA-Z])|GPa|MPa|kPa|Pa|%|percent|pct|seconds?|sec|minutes?|min"
    r"|hours?|h(?![a-zA-Z])|s(?![a-zA-Z])|°|deg(?:rees)?|µε|με|microstrain)",
)
_WORD = re.compile(r"[A-Za-zÀ-ÿµμεε*_\-]+")
_CLAUSE = re.compile(r"(?<!\d)[.;!?](?!\d)|\n")


def _values(token: str) -> list[float]:
    """Numeric readings of a token. "29,500" may be 29500 or 29.5: keep both."""
    t = token.replace("−", "-")
    out = []
    if re.fullmatch(r"-?\d{1,3},\d{3}", t):
        out.append(float(t.replace(",", "")))
    try:
        out.append(float(t.replace(",", ".")))
    except ValueError:
        pass
    return out


def numbers_in_text(text: str) -> list[tuple[str, float]]:
    out = []
    for m in _NUM.finditer(text):
        vals = _values(m.group())
        if vals:
            out.append((m.group(), vals[-1]))
    return out


# ------------------------------------------------------------ data classes


@dataclass(frozen=True)
class Quantity:
    """A number with what it measures. ``value`` is in the base unit of ``dim``."""

    value: float
    dim: str | None  # length | stress | pct | fraction | time | angle | strain | count | volume | None
    qty: str | None  # quantity class, see _QUANTITIES
    origin: str = ""
    factor: float = 1.0  # displayed unit -> base unit


@dataclass
class Finding:
    token: str
    reason: str


@dataclass
class GroundingReport:
    checked: int
    unsupported: list[str] = field(default_factory=list)
    details: list[Finding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.unsupported

    def as_text(self) -> str:
        if self.ok:
            return f"grounding: all {self.checked} numbers trace back to solver output with matching quantity and unit ✓"
        lines = [f"grounding: {len(self.unsupported)} of {self.checked} numbers NOT supported by any tool result:"]
        lines += [f"  - {f.token}: {f.reason}" for f in self.details]
        return "\n".join(lines)


# ---------------------------------------------------------------- parsing


def _qty_from_words(words: list[str]) -> str | None:
    for w in words:
        q = _WORD2Q.get(w.lower().strip("*_-"))
        if q:
            return q
    return None


def _key_info(key: str) -> tuple[str | None, float, str | None]:
    """(dimension, factor, quantity) from a JSON key like ``max_deviation_before_mm``."""
    parts = [p for p in re.split(r"[_\s]+", key.lower()) if p]
    dim, fac = None, 1.0
    if parts and parts[-1] in _UNITS:
        dim, fac = _UNITS[parts[-1]]
    qty = None
    for q, (words, _) in _QUANTITIES.items():  # priority order
        if any(p in words for p in parts) or (q == "strain" and any(p.startswith("eps") for p in parts)):
            qty = q
            break
    if key.lower() in ("seconds", "time_s"):
        dim, fac, qty = "time", 1.0, "time"
    if dim is None and qty is not None:
        dim = _DEFAULT_DIM.get(qty)
    if qty == "fraction" and dim is None:
        dim = "fraction"
    return dim, fac, qty


def quantities_in_text(text: str, origin: str = "text") -> list[tuple[str, Quantity]]:
    """Numbers in prose, each bound to the unit right after it and to the nearest
    quantity word in its clause (words before it, or after it up to the next number)."""
    out = []
    clauses, start = [], 0
    for m in _CLAUSE.finditer(text):
        clauses.append((start, text[start:m.start()]))
        start = m.end()
    clauses.append((start, text[start:]))
    for _, clause in clauses:
        nums = list(_NUM.finditer(clause))
        for i, m in enumerate(nums):
            token = m.group()
            vals = _values(token)
            if not vals:
                continue
            um = _UNIT_AFTER.match(clause, m.end())
            dim, fac, unit_end = None, 1.0, m.end()
            if um:
                u = um.group(1)
                dim, fac = _UNITS.get(u.lower(), _UNITS.get(u, (None, 1.0)))
                unit_end = um.end()
            before = _WORD.findall(clause[: m.start()])[::-1][:8]
            nxt = nums[i + 1].start() if i + 1 < len(nums) else len(clause)
            after = _WORD.findall(clause[unit_end:nxt])[:4]
            qty = _pick_quantity(before, after, dim)
            if dim is None and qty is not None:
                dim = _DEFAULT_DIM.get(qty) if qty not in ("reduction", "fraction") else None
            for v in vals:
                out.append((token, Quantity(v * fac, dim, qty, origin, fac)))
    return out


def _pick_quantity(before: list[str], after: list[str], dim: str | None) -> str | None:
    """Nearest quantity word whose class can carry this unit's dimension."""
    cands = []
    for dist, w in enumerate(before):
        q = _WORD2Q.get(w.lower().strip("*_-"))
        if q:
            cands.append((dist, 0, q))
    for dist, w in enumerate(after):
        q = _WORD2Q.get(w.lower().strip("*_-"))
        if q:
            cands.append((dist, 1, q))
    for _, _, q in sorted(cands):
        if dim is None or dim in _QUANTITIES[q][1]:
            return q
    return None


def quantities_in_obj(obj, key: str = "", origin: str = "tool") -> list[Quantity]:
    """All numbers in a (possibly JSON-encoded) tool result, with the quantity and
    unit named by the key that holds them."""
    if isinstance(obj, str):
        try:
            parsed = json.loads(obj)
        except (json.JSONDecodeError, ValueError):
            return [q for _, q in quantities_in_text(obj, origin)]
        if isinstance(parsed, (dict, list)):
            return quantities_in_obj(parsed, key, origin)
        obj = parsed
    out: list[Quantity] = []
    if isinstance(obj, bool) or obj is None:
        return out
    if isinstance(obj, (int, float)):
        if math.isfinite(obj):
            dim, fac, qty = _key_info(key)
            out.append(Quantity(float(obj) * fac, dim, qty, f"{origin}:{key}"))
        return out
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.extend(quantities_in_obj(v, str(k), origin))
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            out.extend(quantities_in_obj(v, key, origin))
    return out


def numbers_in_obj(obj) -> list[float]:
    return [q.value for q in quantities_in_obj(obj)]


# ---------------------------------------------------------------- matching


def _decimals(token: str) -> int:
    t = token.replace(",", ".").lower().split("e")[0]
    return len(t.split(".")[1]) if "." in t else 0


def _honest_rounding(shown: float, true_display: float, token: str) -> bool:
    """``shown`` is ``true_display`` rounded to the token's precision, and the
    rounding hides at most 5 % of the value ("1 mm" for 1.394 mm is rejected)."""
    t, v = abs(true_display), abs(shown)
    if "e" in token.lower():
        return abs(t - v) <= 0.005 * t + 1e-15
    err = abs(t - v)
    half_ulp = 0.5 * 10 ** (-_decimals(token))
    return err <= half_ulp * (1 + 1e-9) + 1e-12 and (err <= 0.05 * t or err < 1e-12)


def _compatible(a: Quantity, s: Quantity) -> tuple[bool, float]:
    """Can answer quantity ``a`` be a rendering of source ``s``? Returns (ok, scale)
    mapping the source's base value into ``a``'s base unit."""
    if a.qty and s.qty and a.qty != s.qty:
        return False, 1.0
    if a.dim == s.dim:
        return True, 1.0
    if a.dim == "pct" and s.dim == "fraction":
        return True, 100.0
    if a.dim is None and s.dim in ("fraction", "strain", "count"):
        return True, 1.0
    return False, 1.0


def _near(x: float, y: float, rel: float = 0.05) -> bool:
    return abs(abs(x) - abs(y)) <= rel * max(abs(x), abs(y)) + 1e-15


def _why_not(a: Quantity, raw: float, sources: list[Quantity]) -> str:
    if a.dim is None and a.qty is None:
        return "no unit and no named quantity: cannot be tied to any solver output"
    for s in sources:  # same value, wrong quantity or dimension
        comp, _ = _compatible(a, s)
        if not comp and _near(s.value, a.value, 0.005):
            if a.qty and s.qty and a.qty != s.qty:
                return f"value matches {s.origin}, but that is a {s.qty}, not a {a.qty}"
            return f"value matches {s.origin}, but in another dimension ({s.dim}, not {a.dim})"
    for s in sources:
        comp, scale = _compatible(a, s)
        if comp and _near(s.value * scale / a.factor, raw):
            return f"too coarse a rounding of {s.origin} ({s.value * scale / a.factor:.4g})"
    for s in sources:  # same digits after a wrong power-of-ten conversion
        for f in (1e3, 1e-3, 1e6, 1e-6, 100, 0.01):
            comp, scale = _compatible(a, s)
            if comp and _near(s.value * scale * f, a.value, 0.005):
                return f"looks like {s.origin} with a wrong unit conversion (x{f:g})"
    what = " ".join(x for x in (a.qty, f"[{a.dim}]" if a.dim else "") if x)
    return f"no tool result reports this {what}"


def check(answer: str, tool_results: list, user_text: str = "", ignore_small_integers: bool = True) -> GroundingReport:
    """Verify that every number in ``answer`` is supported by a tool result of the
    same quantity and dimension, or by the user's request.

    Unit-less integers <= 12 (list numbering, counts like "3 iterations") are
    structural and skipped; a small integer *with* a physical unit ("2 mm") is checked.
    """
    sources: list[Quantity] = []
    for r in tool_results:
        sources.extend(quantities_in_obj(r))
    sources.extend(q for _, q in quantities_in_text(user_text, "user"))

    report = GroundingReport(checked=0)
    items = quantities_in_text(answer, "answer")
    i = 0
    while i < len(items):
        token = items[i][0]
        n = len(_values(token))
        readings = [q for _, q in items[i : i + n]]
        i += n
        raw = _values(token)[-1]
        a0 = readings[-1]
        if (ignore_small_integers and raw.is_integer() and abs(raw) <= 12 and "." not in token
                and "," not in token and a0.dim in (None, "count")):
            continue
        report.checked += 1
        ok = False
        if a0.dim is None and a0.qty is None:  # unbound: nothing to tie it to
            readings = []
        for a in readings:
            shown = a.value / a.factor
            for s in sources:
                comp, scale = _compatible(a, s)
                if comp and _honest_rounding(shown, s.value * scale / a.factor, token):
                    ok = True
                    break
            if ok:
                break
        if not ok:
            report.unsupported.append(token)
            report.details.append(Finding(token, _why_not(a0, raw, sources)))
    return report
