from pathlib import Path
from src.models import QCResult
from src.utils import log_event, now_iso
from rich.console import Console
from rich.table import Table

console = Console()


def print_qc_summary(qc: QCResult) -> None:
    """Print a formatted QC summary to terminal."""
    status = "[bold green]PASSED[/]" if qc.passed else "[bold red]FAILED[/]"
    console.print(f"\n{'='*50}")
    console.print(f"  QC Report — {qc.plate_id}   {status}")
    console.print(f"{'='*50}")

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Metric", style="dim")
    table.add_column("Value")

    table.add_row("Pos control mean ± SD",
                  f"{qc.pos_control_mean:.0f} ± {qc.pos_control_std:.0f} RFU")
    table.add_row("Neg control mean ± SD",
                  f"{qc.neg_control_mean:.0f} ± {qc.neg_control_std:.0f} RFU")
    table.add_row("Z'-factor",     f"{qc.z_factor:.4f}")
    table.add_row("Signal/background", f"{qc.signal_to_background:.2f}x")
    table.add_row("Missing wells", str(len(qc.missing_wells)))
    table.add_row("Outlier wells", str(len(qc.outlier_wells)))

    console.print(table)

    if qc.failure_reasons:
        console.print("\n[bold red]Failure reasons:[/]")
        for r in qc.failure_reasons:
            console.print(f"  • {r}")
    console.print()

    log_event({
        "event": "report_printed",
        "source": "reporting",
        "target": "scientist",
        "plate_id": qc.plate_id,
        "status": "success",
        "timestamp": now_iso()
    })