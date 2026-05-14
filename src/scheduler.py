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
        self.events: list[SchedulerEvent] = [] #The list starts empty because at the moment the Scheduler object is created, no events have happened yet. 
        #It gets built later inside emit_handoff(), where each new SchedulerEvent object is appended with self.events.append(evt).

    def load_job(self, job_path: str) -> dict: #load_job() returns a dict, because load_json() opens a JSON file, parses it, and turns it into a Python dictionary.
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
        evt = SchedulerEvent( #evt is a Pydantic model object. 
            job_id=job_id,
            plate_id=plate_id,
            event=event,
            source=source,
            target=target,
            status=status,
            timestamp=now_iso(),
            details=details or {} # might be None. If details was given, use it; otherwise use an empty dictionary {}. For example, plate_stored may only need basic fields and no extra notes.
        ) #So this is a safety pattern. Equivalent longer version: 
#if details is None:
#    details = {}
        self.events.append(evt) #stores the event object in memory, inside the scheduler.
        log_event(evt.model_dump()) #model_dump() converts evt into a normal Python dictionary, easier to log as JSON. 
        #log_event(event: dict, log_file: str = "run_log.jsonl"): This function expects event to already be a Python dictionary.
        #takes a dictionary version of the event and writes it as one JSON line into a log file. the list grows over time. 
        #It is an in-memory history of events for the current scheduler run, while run_log.jsonl is the on-disk history written to file line by line.

        # Also save each handoff as its own JSON file for traceability
        out = Path("data/logs") / f"event_{job_id}_{event}.json" #out is just a variable name for the file path. It means “output path” here. this creates a new file for every single event
        #This line creates a file path such as: data/logs/event_JOB_001_read_complete.json. 
        #In a real lab, these would be cleaned up eventually, but here they are kept so you can see exactly what happened at every step (traceability).
        #with this code, one JSON file is written per event type occurrence. In your small project that is acceptable. In a real system, logs might rotate, be archived, or be stored in a database instead.
        out.write_text(json.dumps(evt.model_dump(), indent=2)) #a chain of steps: evt is a SchedulerEvent object. evt.model_dump() turns it into a Python dict.
        # json.dumps(..., indent=2) turns that dict into pretty JSON text. out.write_text(...) writes that text into the file path stored in out.
        #indent: purely for humans. It adds spaces so the file looks like a neat list instead of one long, messy line of text.
        return evt

    def run_job(self, job: dict, reader, stacker,
                pipeline_fn, fail_controls: bool = False) -> dict: #pipeline_fn is a placeholder for the actual QC function, passed into run_job() from outside. fn is common programmer shorthand for Function.
        """
        Execute all steps in the job definition.
        Each step calls a device, waits for completion, emits a handoff.
        """
        job_id = job["job_id"]
        plate_id = job["plate_id"]
        results = {} #a normal dictionary

        for step in job["steps"]:
            device_id = step["device"]
            step_num = step["step"]

            # ── Step 1: plate reader ──────────────────────────────────────
            if step.get("method"):
                method = step["method"]
                reader.start_run(plate_id, method)

                # Poll until complete (in reality: polling loop with timeout)
                for attempt in range(self.max_retries + 1): #range(3) gives: attempt 0 = first try attempt 1 = first retry attempt 2 = second retry. So +1 includes the original attempt plus the retries.
                    status = reader.get_status()
                    if status in ("success", "failed"): 
                        break

                raw_result = reader.fetch_results(
                    plate_id=plate_id,
                    plate_map_path=job["plate_map_file"],
                    job_id=job_id,
                    method=method,
                    fail_controls=fail_controls
                )
                results["raw"] = raw_result #results is a normal dictionary created earlier. Then keys are added to it over time. the dictionary gradually collects outputs from each stage.

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
                qc_result, normalized_df = pipeline_fn(raw_result, job_id) #means “take the two returned values and store them in these two variables.” This line calls a function stored in the variable pipeline_fn.
                #The scheduler does not need to know the exact QC code. It just knows: give raw results to this function, get back QC output and normalized data.
                #That is why you do not see qc.py imported directly in this snippet. It may be wrapped by another function and passed in as pipeline_fn.
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
                results["stored"] = store_result #save the result of the stacker storage step under the key "stored" in the results dictionary. It is not appending to a list. It is assigning a dictionary key.

        return results