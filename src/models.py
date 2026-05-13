from pydantic import BaseModel
from typing import Optional
from datetime import datetime

# These are the data contracts.
# Every function passes these objects around — not raw dicts.
# This catches bugs early: if a field is missing or the wrong type,
# Pydantic raises an error immediately rather than silently breaking downstream.

class WellResult(BaseModel):
    #WellResult is a Pydantic model. A Pydantic model: is a class, has fields, validates data, can convert itself to a dictionary
    #WellResult(well_id="A01", row="A",..., concentration_um=0.0, signal_rfu=3857.1)
    well_id: str
    row: str
    column: int
    well_type: str          # positive_control | negative_control | compound
    compound_id: str
    concentration_um: float
    signal_rfu: float

class RawPlateResult(BaseModel):
    plate_id: str
    job_id: str
    device_id: str
    method: str
    timestamp: str
    wells: list[WellResult]

class QCResult(BaseModel):
    plate_id: str
    job_id: str
    pos_control_mean: float
    pos_control_std: float
    neg_control_mean: float
    neg_control_std: float
    z_factor: float
    signal_to_background: float
    missing_wells: list[str]
    outlier_wells: list[str]
    passed: bool
    failure_reasons: list[str]

class SchedulerEvent(BaseModel):
    job_id: str
    plate_id: str
    event: str              # e.g. read_complete, qc_passed, stored
    source: str             # device or system that emitted the event
    target: str             # next device or system
    status: str             # success | failed
    timestamp: str
    details: Optional[dict] = {}