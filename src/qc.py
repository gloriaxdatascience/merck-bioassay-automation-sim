import numpy as np
import pandas as pd
from scipy import stats
from src.models import RawPlateResult, QCResult
from src.utils import log_event, now_iso, load_json

RULES = load_json("configs/assay_rules.json")

# Read control column definitions from config — single source of truth
POS_COLS = RULES["positive_control_columns"]   # [1, 2]
NEG_COLS = RULES["negative_control_columns"]   # [12]


def run_qc(raw: RawPlateResult, job_id: str) -> tuple[QCResult, pd.DataFrame]:
    """
    Full QC pipeline for one plate.

    Steps:
    1. Check for missing wells vs expected plate format
    2. Identify controls by column number (from assay_rules.json)
    3. Compute control statistics (mean, SD)
    4. Calculate Z'-factor
    5. Calculate signal-to-background ratio
    6. Normalize all wells to percent inhibition
    7. Flag statistical outliers by Z-score
    8. Emit pass/fail verdict
    """

    df = pd.DataFrame([w.model_dump() for w in raw.wells])
    failure_reasons = []

    # ── 1. Missing well check ─────────────────────────────────────────────
    expected_count = RULES["plate_format"]
    missing_wells = []
    if len(df) < expected_count:
        missing = expected_count - len(df)
        missing_wells = [f"MISSING_{i}" for i in range(missing)]
        failure_reasons.append(f"{missing} wells missing from raw data")

    # ── 2. Identify controls by column (config-driven) ────────────────────
    # This is the correct pattern: the config defines plate layout,
    # not the well_type label in the plate map. In real labs the config
    # is set by the assay developer and treated as the authority.
    pos_mask = df["column"].isin(POS_COLS)
    neg_mask = df["column"].isin(NEG_COLS)

    pos = df[pos_mask]["signal_rfu"].values
    neg = df[neg_mask]["signal_rfu"].values

    min_controls = 2
    if len(pos) < min_controls:
        failure_reasons.append(
            f"Only {len(pos)} positive control wells found in columns {POS_COLS} "
            f"(need ≥{min_controls})"
        )
    if len(neg) < min_controls:
        failure_reasons.append(
            f"Only {len(neg)} negative control wells found in columns {NEG_COLS} "
            f"(need ≥{min_controls})"
        )

    # ── 3. Control statistics ─────────────────────────────────────────────
    pos_mean = float(np.mean(pos)) if len(pos) > 0 else 0.0
    pos_std  = float(np.std(pos))  if len(pos) > 0 else 0.0
    neg_mean = float(np.mean(neg)) if len(neg) > 0 else 0.0
    neg_std  = float(np.std(neg))  if len(neg) > 0 else 0.0

    # ── 4. Z'-factor ──────────────────────────────────────────────────────
    # Z' = 1 - (3*SD_pos + 3*SD_neg) / |mean_pos - mean_neg|
    # >0.5 excellent | 0–0.5 marginal | <0 failed
    denom = abs(pos_mean - neg_mean)
    if denom == 0:
        z_factor = -1.0
        failure_reasons.append("Z-factor undefined: control means are equal")
    else:
        z_factor = float(1 - (3 * pos_std + 3 * neg_std) / denom)

    if z_factor < RULES["pass_criteria"]["z_factor"]:
        failure_reasons.append(
            f"Z'-factor {z_factor:.3f} below threshold "
            f"{RULES['pass_criteria']['z_factor']}"
        )

    # ── 5. Signal-to-background ───────────────────────────────────────────
    s2b = (pos_mean / neg_mean) if neg_mean > 0 else 0.0
    if s2b < RULES["pass_criteria"]["signal_to_background"]:
        failure_reasons.append(
            f"Signal-to-background {s2b:.2f} below threshold "
            f"{RULES['pass_criteria']['signal_to_background']}"
        )

    # ── 6. Percent inhibition normalization ───────────────────────────────
    # %inhib = (mean_pos - signal) / (mean_pos - mean_neg) * 100
    # 100% = fully inhibited | 0% = no effect
    if denom > 0:
        df["percent_inhibition"] = (
            (pos_mean - df["signal_rfu"]) / (pos_mean - neg_mean) * 100
        ).round(2)
    else:
        df["percent_inhibition"] = 0.0

    # ── 7. Outlier detection (compound wells only) ────────────────────────
    compound_mask = ~df["column"].isin(POS_COLS + NEG_COLS)
    compound_df = df[compound_mask].copy()
    df["outlier"] = False

    if len(compound_df) > 3:
        zscores = np.abs(stats.zscore(compound_df["signal_rfu"]))
        threshold = RULES["outlier_zscore_threshold"]
        outlier_idx = compound_df[zscores > threshold].index
        outlier_wells = compound_df.loc[outlier_idx, "well_id"].tolist()
        df.loc[outlier_idx, "outlier"] = True
    else:
        outlier_wells = []

    # ── 8. Pass/fail verdict ──────────────────────────────────────────────
    passed = len(failure_reasons) == 0

    qc_result = QCResult(
        plate_id=raw.plate_id,
        job_id=job_id,
        pos_control_mean=round(pos_mean, 2),
        pos_control_std=round(pos_std, 2),
        neg_control_mean=round(neg_mean, 2),
        neg_control_std=round(neg_std, 2),
        z_factor=round(z_factor, 4),
        signal_to_background=round(s2b, 4),
        missing_wells=missing_wells,
        outlier_wells=outlier_wells,
        passed=passed,
        failure_reasons=failure_reasons
    )

    log_event({
        "event": "qc_complete",
        "source": "qc_module",
        "target": "reporting",
        "plate_id": raw.plate_id,
        "status": "success" if passed else "failed",
        "timestamp": now_iso(),
        "details": {
            "z_factor": round(z_factor, 3),
            "s2b": round(s2b, 2),
            "pos_control_wells": int(len(pos)),
            "neg_control_wells": int(len(neg)),
            "passed": passed,
            "failure_reasons": failure_reasons
        }
    })

    return qc_result, df