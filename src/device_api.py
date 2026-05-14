import random
import time
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd

from src.models import WellResult, RawPlateResult
#models.py imports Pydantic to build the classes. device_api.py imports the classes from models.py.
#Because the classes "carry" their own functions with them, device_api.py can use model_dump() without ever knowing Pydantic exists.
from src.utils import log_event, now_iso, save_json

RAW_DIR = Path("data/raw")
RAW_DIR.mkdir(parents=True, exist_ok=True)


class MockPlateReader:
    """
    Simulates a PerkinElmer EnVision fluorescence plate reader.

    In a real integration, replace the internals of each method
    with calls to the vendor's REST API or SDK. The method signatures
    stay identical — that's the point of the wrapper pattern.
    The scheduler never needs to know what's underneath.
    """

    def __init__(self, device_id: str, name: str): #"Setup"/"Assembly" function. self refers to the specific machine currently running.
        #If there are two plate readers, self ensures that when you ask Reader A for its status, it doesn't give you the status of Reader B.
        #functions must always take self as their first argument so they know which specific object's data they are working with.
        self.device_id = device_id
        self.name = name
        self._status = "idle"
        self._current_job = None

    def start_run(self, plate_id: str, method_name: str) -> dict: #dict: Dictionaries. They store data in "Key: Value" pairs. 
        """
        Command the reader to begin a measurement run.
        Returns a job handle immediately — status must be polled separately.
        When you tell a robot to start a 10-minute scan, the software doesn't sit and wait for 10 minutes. It immediately gives you a "Ticket" (the job handle) and moves on to other tasks.
        "Because the software moved on, it doesn't know when the robot finishes. 
        To find out, you must use a separate function (get_status) to "Poll" (ask) the instrument: "Are you done yet?" until it answers "Idle".
        """
        self._status = "running"
        self._current_job = plate_id
        log_event({ #from src.utils import log_event. {}: Dictionaries. They store data in "Key: Value" pairs
            "event": "run_started",
            "source": self.device_id,
            "target": "plate_reader",
            "plate_id": plate_id,
            "status": "success",
            "timestamp": now_iso(),
            "details": {"method": method_name}
        })
        time.sleep(0.3)   # 0.3 second simulates network + instrument latency
        return {"job_id": f"{plate_id}_PR", "status": "running"} #f stands for Format. It allows you to put a variable directly into a piece of text. If plate_id is "PLT_001", then f"{plate_id}_PR" becomes "PLT_001_PR".

    def get_status(self) -> str:
        """Poll the instrument for current state."""
        return self._status

    def fetch_results(self, plate_id: str, plate_map_path: str,
                      job_id: str, method: str,
                      fail_controls: bool = False) -> RawPlateResult: 
        #This False is a Default Value. If you don't mention it when calling the function, Python assumes it is False.
        #->: a Type Hint. It is a label telling you (and the editor) that when this function finishes, it will give you back a RawPlateResult object.
        """
        Read measurement values for every well.
        Merges with the plate map so every result carries biological context.

        fail_controls=True simulates a bad run for the failure scenario.
        """
        plate_map = pd.read_csv(plate_map_path) #a DataFrame created from CSV
        wells = [] #List, ordered. 

        for _, row in plate_map.iterrows(): 
            #Well A1, then A2, then A3... create "realistic" fake numbers. 
            #.iterrows() is deterministic: It reads the CSV from top to bottom. It yields rows in that exact order.
            #iterrows() returns two things: the row index (0, 1, 2, 3…) and the row data: (index, row)
            #_ is just a variable name. Python does NOT treat it specially.
            #But programmers use _ to mean: “I am receiving this value, but I will not use it.” It’s a signal to humans, not to Python.
            #or: for banana, row in plate_map.iterrows():
            #But you don’t need the index. So Python convention says: “If you don’t need a variable, name it _.” It means throw it away.
            wtype = row["well_type"]

            if fail_controls:
                #the machine "breaks" and gives random messy numbers (around 5,000) for everything. Simulate a broken assay: controls look like compounds
                signal = round(random.gauss(5000, 2000), 2)
            elif wtype == "positive_control":
                signal = round(random.gauss(28000, 600), 2)
            elif wtype == "negative_control":
                signal = round(random.gauss(1000, 100), 2)
            else:
                signal = round(random.gauss(14000, 3000), 2)

            wells.append(WellResult( #wells is a list containing many WellResult objects. Each time the loop processes one row, it creates one WellResult object.
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
            wells=wells #Python executes code line by line. The wells list is built one well at a time in the loop, and only when the loop is 100% finished does the code move down to create the result.
        )

        # Save raw CSV exactly as a real instrument would export it
        raw_path = RAW_DIR / f"plate_reader_output_{plate_id}.csv"
        df = pd.DataFrame([w.model_dump() for w in wells]) #export the contents. It takes the data trapped inside the WellResult object and turns it into a simple Python dictionary.
        #model_dump(): Turns a Pydantic object into a dictionary.
        #[w.model_dump() for w in wells]: Take every WellResult object in the wells list one by one, call it w, run model_dump() on it - convert the object to a plain dictionary:
        #{"well_id": "A01", "row": "A",..., "concentration_um": 0.0, "signal_rfu": 3857.1}
        #[{dict for A01}, {dict for A02}, {dict for A03},...]
        #pd.DataFrame(...) takes that new list of dictionaries and "stacks" them to create a table.

        df.to_csv(raw_path, index=False) #saves that table as a permanent file and tells Python not to add an extra column for row numbers (0, 1, 2...) so the file stays clean for other software to read.

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