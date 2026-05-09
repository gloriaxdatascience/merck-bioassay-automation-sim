from pathlib import Path
import pandas as pd
from src.models import RawPlateResult, QCResult
from src.qc import run_qc
from src.utils import save_json, now_iso, log_event

PROCESSED_DIR = Path("data/processed")
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


def run_pipeline(raw: RawPlateResult, job_id: str) -> tuple[QCResult, pd.DataFrame]:
    """
    Runs QC on raw plate data, saves normalized results,
    and exports a Genedata-style import CSV.
    """
    qc_result, normalized_df = run_qc(raw, job_id)

    # Save QC report as JSON
    qc_path = PROCESSED_DIR / f"qc_report_{raw.plate_id}.json"
    save_json(qc_result.model_dump(), str(qc_path))

    # Save normalized results CSV
    norm_path = PROCESSED_DIR / f"normalized_results_{raw.plate_id}.csv"
    normalized_df.to_csv(norm_path, index=False)

    # Export Genedata-style import file
    genedata_path = PROCESSED_DIR / f"genedata_import_{raw.plate_id}.csv"
    _export_genedata(normalized_df, raw, qc_result, str(genedata_path))

    log_event({
        "event": "pipeline_complete",
        "source": "pipeline",
        "target": "genedata",
        "plate_id": raw.plate_id,
        "status": "success" if qc_result.passed else "failed",
        "timestamp": now_iso(),
        "details": {
            "qc_report": str(qc_path),
            "normalized": str(norm_path),
            "genedata_export": str(genedata_path)
        }
    })

    return qc_result, normalized_df


def _export_genedata(df: pd.DataFrame, raw: RawPlateResult,
                     qc: QCResult, out_path: str) -> None:
    """
    Genedata Screener expects a specific column layout for import.
    This formatter produces a clean CSV matching that contract.
    In a real integration, exact column names come from the Genedata admin.
    """
    gd = df[df["well_type"] == "compound"].copy()
    gd = gd.rename(columns={
        "well_id": "Well",
        "compound_id": "Compound_ID",
        "concentration_um": "Concentration_uM",
        "signal_rfu": "Raw_Signal",
        "percent_inhibition": "Percent_Inhibition"
    })
    gd["Plate_ID"] = raw.plate_id
    gd["Job_ID"] = raw.job_id
    gd["Assay_Method"] = raw.method
    gd["Z_Factor"] = qc.z_factor
    gd["Plate_Pass"] = qc.passed
    gd["Outlier"] = gd.get("outlier", False)
    gd["Timestamp"] = raw.timestamp

    cols = [
        "Plate_ID", "Job_ID", "Well", "Compound_ID",
        "Concentration_uM", "Raw_Signal", "Percent_Inhibition",
        "Outlier", "Z_Factor", "Plate_Pass", "Assay_Method", "Timestamp"
    ]
    gd[cols].to_csv(out_path, index=False)