from src.device_api import MockPlateReader, MockStacker


def test_plate_reader_returns_correct_well_count():
    """
    fetch_results must return exactly one WellResult per row in the plate map.
    Our plate_map_001.csv has 96 wells — any other count means a parsing bug.
    """
    reader = MockPlateReader(device_id="PR_TEST", name="TestReader")
    reader.start_run("PLT_TEST", "HTRF_Assay")
    result = reader.fetch_results(
        plate_id="PLT_TEST",
        plate_map_path="data/input/plate_map_001.csv",
        job_id="JOB_TEST",
        method="HTRF_Assay"
    )
    assert len(result.wells) == 96, (
        f"Expected 96 wells, got {len(result.wells)}. "
        "Check that plate_map_001.csv has not been modified."
    )


def test_full_stacker_returns_failed_status():
    """
    A stacker at capacity must reject new plates with status='failed'.
    This simulates a real automation failure mode: stacker overflow.
    The scheduler must handle this gracefully rather than silently losing a plate.
    """
    stacker = MockStacker(device_id="ST_TEST", capacity=2)
    stacker.store_plate("PLT_A")
    stacker.store_plate("PLT_B")   # now full
    result = stacker.store_plate("PLT_C")  # this must fail
    assert result["status"] == "failed"
    assert result["reason"] == "stacker_full"