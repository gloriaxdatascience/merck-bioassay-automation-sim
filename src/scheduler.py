import json
from pathlib import Path
from src.utils import log_event, now_iso, load_json
from src.models import SchedulerEvent


class Scheduler:
    """
    Reads a job definition (JSON) and executes each step in sequence.

    The key responsibility of the scheduler is the handoff signal:
    when one device finishes, it emits a SchedulerEvent that tells
    the next device to begin. This is the JSON message pattern the
    hiring manager described — 'when the plate reader finishes,
    send a JSON signal to move the plate to the stacker.'
    """

    def __init__(self, config_path: str = "configs/scheduler_config.json"):
        self.config = load_json(config_path)
        self.max_retries = self.config["max_retries"]
        self.events: list[SchedulerEvent] = []

    def load_job(self, job_path: str) -> dict:
        job = load_json(job_path)
        log_event({
            "event": "job_received",
            "source": "scheduler",
            "target": job["steps"][0]["device"],
            "plate_id": job["plate_id"],
            "status": "success",
            "timestamp": now_iso(),
            "details": {"job_id": job["job_id"], "assay": job["assay_name"]}
        })
        return job

    def emit_handoff(self, job_id: str, plate_id: str,
                     event: str, source: str, target: str,
                     status: str, details: dict = None) -> SchedulerEvent:
        """
        Emit the structured JSON handoff signal between devices.
        This is logged and returned so the pipeline can react to it.
        """
        evt = SchedulerEvent(
            job_id=job_id,
            plate_id=plate_id,
            event=event,
            source=source,
            target=target,
            status=status,
            timestamp=now_iso(),
            details=details or {}
        )
        self.events.append(evt)
        log_event(evt.model_dump())

        # Also save each handoff as its own JSON file for traceability
        out = Path("data/logs") / f"event_{job_id}_{event}.json"
        out.write_text(json.dumps(evt.model_dump(), indent=2))
        return evt

    def run_job(self, job: dict, reader, stacker,
                pipeline_fn, fail_controls: bool = False) -> dict:
        """
        Execute all steps in the job definition.
        Each step calls a device, waits for completion, emits a handoff.
        """
        job_id = job["job_id"]
        plate_id = job["plate_id"]
        results = {}

        for step in job["steps"]:
            device_id = step["device"]
            step_num = step["step"]

            # ── Step 1: plate reader ──────────────────────────────────────
            if step.get("method"):
                method = step["method"]
                reader.start_run(plate_id, method)

                # Poll until complete (in reality: polling loop with timeout)
                for attempt in range(self.max_retries + 1):
                    status = reader.get_status()
                    if status in ("idle", "running"):
                        break

                raw_result = reader.fetch_results(
                    plate_id=plate_id,
                    plate_map_path=job["plate_map_file"],
                    job_id=job_id,
                    method=method,
                    fail_controls=fail_controls
                )
                results["raw"] = raw_result

                # Handoff signal: reader → pipeline
                self.emit_handoff(
                    job_id, plate_id,
                    event="read_complete",
                    source=device_id,
                    target="pipeline",
                    status="success",
                    details={"method": method}
                )

                # Run QC + normalization
                qc_result, normalized_df = pipeline_fn(raw_result, job_id)
                results["qc"] = qc_result

                qc_status = "success" if qc_result.passed else "failed"
                self.emit_handoff(
                    job_id, plate_id,
                    event="qc_complete",
                    source="pipeline",
                    target=device_id,
                    status=qc_status,
                    details={"z_factor": round(qc_result.z_factor, 3),
                             "passed": qc_result.passed}
                )

            # ── Step 2: stacker ───────────────────────────────────────────
            elif step.get("action") == "store":
                store_result = stacker.store_plate(plate_id)
                self.emit_handoff(
                    job_id, plate_id,
                    event="plate_stored",
                    source=stacker.device_id,
                    target="archive",
                    status=store_result["status"]
                )
                results["stored"] = store_result

        return results