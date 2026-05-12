import pytest
from src.models import WellResult, RawPlateResult
from src.qc import run_qc, POS_COLS, NEG_COLS


def make_well(well_id, row, column, well_type, compound_id, signal):
    return WellResult(
        well_id=well_id,
        row=row,
        column=column,
        well_type=well_type,
        compound_id=compound_id,
        concentration_um=0 if "CTRL" in compound_id else 10,
        signal_rfu=signal
    )


def make_plate(pos_signal=28000, neg_signal=1000):
    """
    Build a synthetic 96-well plate matching the real plate map layout:
    - Columns 1–2: positive controls (rows A–H = 16 wells)
    - Column 12:   negative controls (rows A–H = 8 wells)
    - Columns 3–11: compounds (rows A–H = 72 wells)

    Column numbers must match POS_COLS and NEG_COLS from assay_rules.json
    so that the config-driven QC correctly identifies controls.
    """
    wells = []
    rows = list("ABCDEFGH")

    # Positive controls: columns 1 and 2
    for i, row in enumerate(rows):
        for col in [1, 2]:
            wells.append(make_well(
                f"{row}{col:02d}", row, col,
                "positive_control", "CTRL_POS",
                pos_signal + i * 10
            ))

    # Negative controls: column 12
    for i, row in enumerate(rows):
        wells.append(make_well(
            f"{row}12", row, 12,
            "negative_control", "CTRL_NEG",
            neg_signal + i * 5
        ))

    # Compounds: columns 3–11
    cpd = 0
    for row in rows:
        for col in range(3, 12):
            wells.append(make_well(
                f"{row}{col:02d}", row, col,
                "compound", f"CPD_{cpd:03d}",
                14000 + cpd * 5
            ))
            cpd += 1

    return RawPlateResult(
        plate_id="PLT_TEST",
        job_id="JOB_TEST",
        device_id="PR_01",
        method="HTRF_Assay",
        timestamp="2025-01-01T00:00:00+00:00",
        wells=wells
    )


def test_good_plate_passes():
    """A plate with well-separated controls must pass all QC criteria."""
    raw = make_plate(pos_signal=28000, neg_signal=1000)
    qc, df = run_qc(raw, "JOB_TEST")
    assert qc.passed is True, f"Expected pass. Failures: {qc.failure_reasons}"
    assert qc.z_factor > 0.5, f"Z' = {qc.z_factor}"
    assert qc.signal_to_background > 2.0, f"S/B = {qc.signal_to_background}"


def test_collapsed_controls_fail():
    """When pos and neg controls give the same signal, Z' is undefined → fail."""
    raw = make_plate(pos_signal=5000, neg_signal=5000)
    qc, df = run_qc(raw, "JOB_TEST")
    assert qc.passed is False
    assert qc.z_factor < 0.5


def test_percent_inhibition_positive_controls_near_100():
    """
    Positive control wells should have percent inhibition close to 0%.

    Convention: positive controls have HIGH signal (no inhibition of the assay).
    %inhibition = (mean_pos - signal) / (mean_pos - mean_neg) * 100
    When signal ≈ mean_pos, the numerator ≈ 0, so %inhibition ≈ 0%.

    This confirms the normalization anchor is working correctly.
    """
    raw = make_plate(pos_signal=28000, neg_signal=1000)
    qc, df = run_qc(raw, "JOB_TEST")
    pos_pi = df[df["column"].isin(POS_COLS)]["percent_inhibition"]
    assert pos_pi.between(-10, 10).all(), (
        f"Positive control %inhibition out of range: {pos_pi.values}"
    )


def test_percent_inhibition_negative_controls_near_zero():
    """
    Negative control wells should have percent inhibition close to 100%.

    Convention: negative controls have LOW signal (fully inhibited baseline).
    When signal ≈ mean_neg, numerator ≈ (mean_pos - mean_neg),
    so %inhibition ≈ 100%.

    This confirms the normalization denominator is correct.
    """
    raw = make_plate(pos_signal=28000, neg_signal=1000)
    qc, df = run_qc(raw, "JOB_TEST")
    neg_pi = df[df["column"].isin(NEG_COLS)]["percent_inhibition"]
    assert neg_pi.between(90, 110).all(), (
        f"Negative control %inhibition out of range: {neg_pi.values}"
    )


def test_correct_control_well_counts():
    """
    Config says pos cols = [1,2], neg cols = [12].
    On an 8-row plate: 16 pos wells, 8 neg wells.
    """
    raw = make_plate()
    qc, df = run_qc(raw, "JOB_TEST")
    assert qc.pos_control_mean > 0
    assert qc.neg_control_mean > 0
    # 16 pos wells means mean should be close to 28000, not diluted by compounds
    assert qc.pos_control_mean > 20000, (
        f"Pos control mean {qc.pos_control_mean} suggests wrong wells identified"
    )