"""
main.py — run one end-to-end bioassay automation job.

Runs twice:
  1. Normal run  → Z' > 0.5, plate passes QC
  2. Failed run  → controls broken, Z' fails, plate flagged

This directly simulates what the Merck lab does:
every plate gets QC'd before results are trusted.
"""

from src.device_api import MockPlateReader, MockStacker
from src.scheduler import Scheduler
from src.pipeline import run_pipeline
from src.reporting import print_qc_summary
from src.utils import load_json, log_event, now_iso


def run(job_path: str, fail_controls: bool = False) -> None:
    tag = "[FAILURE SCENARIO]" if fail_controls else "[NORMAL RUN]"
    print(f"\n{'#'*55}")
    print(f"  {tag}")
    print(f"{'#'*55}\n")

    # Instantiate devices (in reality: loaded from instrument_config.json)
    reader  = MockPlateReader(device_id="PR_01", name="EnVision")
    stacker = MockStacker(device_id="ST_01", capacity=50)
    scheduler = Scheduler()

    # Load the job
    job = scheduler.load_job(job_path)

    # Execute: scheduler drives reader → pipeline → stacker
    results = scheduler.run_job(
        job=job,
        reader=reader,
        stacker=stacker,
        pipeline_fn=run_pipeline,
        fail_controls=fail_controls
    )

    # Print QC summary to terminal
    print_qc_summary(results["qc"])

    final_status = "passed" if results["qc"].passed else "failed"
    log_event({
        "event": "job_finished",
        "source": "main",
        "target": "scientist",
        "plate_id": job["plate_id"],
        "status": final_status,
        "timestamp": now_iso(),
        "details": {"job_id": job["job_id"]}
    })


if __name__ == "__main__":
    JOB = "data/input/scheduler_job_001.json"

    # Run 1: healthy assay
    run(JOB, fail_controls=False)

    # Run 2: broken controls — simulates instrument or reagent failure
    run(JOB, fail_controls=True)