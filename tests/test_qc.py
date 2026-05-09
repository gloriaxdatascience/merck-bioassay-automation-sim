import pytest
from src.models import WellResult, RawPlateResult
from src.qc import run_qc


def make_plate(pos_signal=28000, neg_signal=1000, n_pos=16, n_neg=16):
    """Helper: build a synthetic plate with known control values."""
    wells = []
    # Positive controls
    for i in range(n_pos):
        wells.append(WellResult(
            well_id=f"A{i+1:02d}", row="A", column=i+1,
            well_type="positive_control",
            compound_id="CTRL_POS", concentration_um=0,
            signal_rfu=pos_signal + (i * 10)
        ))
    # Negative controls
    for i in range(n_neg):
        wells.append(WellResult(
            well_id=f"H{i+1:02d}", row="H", column=i+1,
            well_type="negative_control",
            compound_id="CTRL_NEG", concentration_um=0,
            signal_rfu=neg_signal + (i * 5)
        ))
    # Compounds
    for i in range(64):
        wells.append(WellResult(
            well_id=f"B{i+1:02d}", row="B", column=(i % 24) + 1,
            well_type="compound",
            compound_id=f"CPD_{i:03d}", concentration_um=10,
            signal_rfu=14000
        ))
    return RawPlateResult(
        plate_id="PLT_TEST",
        job_id="JOB_TEST",
        device_id="PR_01",
        method="HTRF_Assay",
        timestamp="2025-01-01T00:00:00+00:00",
        wells=wells
    )


def test_good_plate_passes():
    raw = make_plate(pos_signal=28000, neg_signal=1000)
    qc, df = run_qc(raw, "JOB_TEST")
    assert qc.passed is True
    assert qc.z_factor > 0.5
    assert qc.signal_to_background > 2.0


def test_collapsed_controls_fail():
    """When pos and neg controls give the same signal, Z' is undefined → fail."""
    raw = make_plate(pos_signal=5000, neg_signal=5000)
    qc, df = run_qc(raw, "JOB_TEST")
    assert qc.passed is False
    assert qc.z_factor < 0.5


def test_percent_inhibition_range():
    """Percent inhibition for compounds should be between -50 and 150 in normal runs."""
    raw = make_plate(pos_signal=28000, neg_signal=1000)
    qc, df = run_qc(raw, "JOB_TEST")
    compound_pi = df[df["well_type"] == "compound"]["percent_inhibition"]
    assert compound_pi.between(-50, 150).all()