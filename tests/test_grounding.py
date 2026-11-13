from prewarp.grounding import check, numbers_in_text


def test_numbers_parsed_including_decimal_comma_and_unicode_minus():
    vals = [v for _, v in numbers_in_text("tip 1,276 mm, eps −0.0037 and 3e-3")]
    assert vals == [1.276, -0.0037, 0.003]


def test_rounded_and_converted_values_are_grounded():
    tools = [{"max_deviation_before_mm": 1.06691, "max_deviation_after_mm": 0.0016986, "reduction_pct": 99.8408}]
    answer = "Distortion drops from 1.07 mm to 1.7 µm (99.8 % less)."
    rep = check(answer, tools)
    assert rep.ok, rep.as_text()


def test_invented_number_is_flagged():
    tools = [{"max_displacement_mm": 0.412}]
    rep = check("Max displacement is 0.41 mm and the stress peaks at 870 MPa.", tools)
    assert not rep.ok
    assert rep.unsupported == ["870"]


def test_small_integers_are_structural_and_skipped():
    rep = check("Step 1: run 3 iterations on 2 orientations.", [])
    assert rep.ok and rep.checked == 0


def test_numbers_from_user_request_are_allowed():
    rep = check("Analysed at 0.5 mm pitch as requested.", [], user_text="use pitch 0.5")
    assert rep.ok


# --- adversarial cases: a value-only check would accept all of these ----------

TOOL = {
    "pitch_mm": 0.5,
    "max_deviation_before_mm": 1.394,
    "max_deviation_after_mm": 0.0037,
    "max_offset_applied_mm": 1.418,
    "eps_xy": -0.00374,
    "von_mises_p99_MPa": 612.0,
    "volume_fraction_above_yield": 0.12,
    "elements": 29500,
    "seconds": 25.3,
    "iterations": [{"iteration": 0, "max_deviation_mm": 1.394}, {"iteration": 1, "max_deviation_mm": 0.064}],
}


def _flags(answer):
    rep = check(answer, [TOOL])
    return rep.unsupported, rep


def test_trivial_number_coinciding_with_another_quantity_is_flagged():
    bad, rep = _flags("The tip warps 0.5 mm after cutting.")  # 0.5 is the pitch, not a distortion
    assert bad == ["0.5"], rep.as_text()
    assert "size" in rep.details[0].reason


def test_small_integers_with_a_unit_are_checked():
    assert _flags("The part distorts by 2 mm.")[0] == ["2"]
    assert _flags("Stress stays below 1 MPa.")[0] == ["1"]


def test_coarse_rounding_that_hides_the_value_is_flagged():
    assert _flags("Max deviation is 1 mm before compensation.")[0] == ["1"]  # true 1.394
    assert _flags("After compensation the residual deviation is 0 mm.")[0] == ["0"]  # true 0.0037


def test_wrong_unit_conversion_is_flagged():
    bad, rep = _flags("After compensation the deviation is 3.7 mm.")  # it is 3.7 µm
    assert bad == ["3.7"] and "conversion" in rep.details[0].reason
    bad, rep = _flags("Max deviation 1.39 MPa.")  # right digits, wrong dimension
    assert bad == ["1.39"]


def test_invented_and_derived_percentages_are_flagged():
    # 1.394 -> 0.0037 is a 99.7 % reduction, but no tool reported a reduction.
    assert _flags("Compensation gives a 99.7 % reduction.")[0] == ["99.7"]
    assert _flags("Printing time drops 35 %.")[0] == ["35"]


def test_number_bound_to_the_wrong_quantity_is_flagged():
    # 1.418 mm is the applied offset, not the deviation.
    bad, rep = _flags("The deviation is 1.418 mm.")
    assert bad == ["1.418"] and "offset" in rep.details[0].reason


def test_bare_number_without_unit_or_quantity_is_flagged():
    bad, rep = _flags("The answer is 0.00374.")
    assert bad == ["0.00374"] and "no unit" in rep.details[0].reason


def test_realistic_honest_answer_passes():
    answer = (
        "With ε* = −0.00374 the bridge deviates 1.39 mm (1394 µm) before compensation. "
        "After the second iteration the max deviation is 3.7 µm; the applied offset is 1.42 mm. "
        "The 99th-percentile von Mises stress is 612 MPa and 12 % of the volume fraction is above yield. "
        "The mesh has 29,500 elements and the solve took 25 s at 0.5 mm pitch."
    )
    rep = check(answer, [TOOL])
    assert rep.ok, rep.as_text()
    assert rep.checked >= 9
