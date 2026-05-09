import random
import time
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd

from src.models import WellResult, RawPlateResult
from src.utils import log_event, now_iso, save_json

RAW_DIR = Path("data/raw")
RAW_DIR.mkdir(parents=True, exist_ok=True)


class MockPlateReader:
    """
    Simulates a PerkinElmer EnVision fluorescence plate reader.

    In a real integration you would replace the internals of each method
    with calls to the vendor's REST API or SDK. The method signatures
    stay identical — that's the point of the wrapper pattern.
    The scheduler never needs to know what's underneath.
    """

    def __init__(self, device_id: str, name: str):
        self.device_id = device_id
        self.name = name
        self._status = "idle"
        self._current_job = None

    def start_run(self, plate_id: str, method_name: str) -> dict:
        """
        Command the reader to begin a measurement run.
        Returns a job handle immediately — status must be polled separately.
        """
        self._status = "running"
        self._current_job = plate_id
        log_event({
            "event": "run_started",
            "source": self.device_id,
            "target": "plate_reader",
            "plate_id": plate_id,
            "status": "success",
            "timestamp": now_iso(),
            "details": {"method": method_name}
        })
        time.sleep(0.3)   # simulates network + instrument latency
        return {"job_id": f"{plate_id}_PR", "status": "running"}

    def get_status(self) -> str:
        """Poll the instrument for current state."""
        return self._status

    def fetch_results(self, plate_id: str, plate_map_path: str,
                      job_id: str, method: str,
                      fail_controls: bool = False) -> RawPlateResult:
        """
        Read measurement values for every well.
        Merges with the plate map so every result carries biological context.

        fail_controls=True simulates a bad run for the failure scenario.
        """
        plate_map = pd.read_csv(plate_map_path)
        wells = []

        for _, row in plate_map.iterrows():
            wtype = row["well_type"]

            if fail_controls:
                # Simulate a broken assay: controls look like compounds
                signal = round(random.gauss(5000, 2000), 2)
            elif wtype == "positive_control":
                signal = round(random.gauss(28000, 600), 2)
            elif wtype == "negative_control":
                signal = round(random.gauss(1000, 100), 2)
            else:
                signal = round(random.gauss(14000, 3000), 2)

            wells.append(WellResult(
                well_id=row["well_id"],
                row=row["row"],
                column=int(row["column"]),
                well_type=wtype,
                compound_id=row["compound_id"],
                concentration_um=float(row["concentration_um"]),
                signal_rfu=max(0.0, signal)
            ))

        result = RawPlateResult(
            plate_id=plate_id,
            job_id=job_id,
            device_id=self.device_id,
            method=method,
            timestamp=now_iso(),
            wells=wells
        )

        # Save raw CSV exactly as a real instrument would export it
        raw_path = RAW_DIR / f"plate_reader_output_{plate_id}.csv"
        df = pd.DataFrame([w.model_dump() for w in wells])
        df.to_csv(raw_path, index=False)

        self._status = "idle"
        log_event({
            "event": "run_complete",
            "source": self.device_id,
            "target": "pipeline",
            "plate_id": plate_id,
            "status": "success",
            "timestamp": now_iso(),
            "details": {"output_file": str(raw_path), "well_count": len(wells)}
        })
        return result


class MockStacker:
    """
    Simulates a plate hotel / stacker.
    Receives plates from the robotic arm after measurement.
    In reality: communicates via TCP socket or vendor CLI.
    """

    def __init__(self, device_id: str, capacity: int = 50):
        self.device_id = device_id
        self.capacity = capacity
        self._stored: list[str] = []

    def store_plate(self, plate_id: str) -> dict:
        if len(self._stored) >= self.capacity:
            log_event({
                "event": "store_failed",
                "source": self.device_id,
                "target": "stacker",
                "plate_id": plate_id,
                "status": "failed",
                "timestamp": now_iso(),
                "details": {"reason": "stacker_full"}
            })
            return {"status": "failed", "reason": "stacker_full"}

        self._stored.append(plate_id)
        log_event({
            "event": "plate_stored",
            "source": self.device_id,
            "target": "stacker",
            "plate_id": plate_id,
            "status": "success",
            "timestamp": now_iso(),
            "details": {"slot": len(self._stored)}
        })
        return {"status": "success", "slot": len(self._stored)}