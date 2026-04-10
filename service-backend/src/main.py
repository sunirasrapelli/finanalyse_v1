#!/usr/bin/env python3
"""
Financial Analysis AI — CLI Orchestrator

Usage
-----
# From a PDF annual report
python main.py --input reports/HDFC_AR_2024.pdf --company "HDFC Bank" --years "2022,2023,2024"

# From a pre-structured JSON file (API call not required)
python main.py --input tests/sample_data/tcs_fy2022_2024.json
"""
import argparse
import sys
import time
from pathlib import Path
from typing import List, Optional

from utils.logger import get_logger

log = get_logger(__name__)

# Default fiscal year window when none are specified
_DEFAULT_YEAR_START = 2022
_DEFAULT_YEAR_END   = 2025   # exclusive — range(2022, 2025) → [2022, 2023, 2024]
_DIVIDER = "=" * 60


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="AI Financial Analysis Automation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--input",      required=True,
                   help="Path to PDF annual report or JSON data file")
    p.add_argument("--company",    default="",
                   help="Company name (required for PDF input)")
    p.add_argument("--years",      default="",
                   help="Comma-separated fiscal years, e.g. '2022,2023,2024'")
    p.add_argument("--currency",   default="INR",
                   help="Currency code (default: INR)")
    p.add_argument("--unit",       default="Crores",
                   help="Reporting unit: Crores or Millions (default: Crores)")
    p.add_argument("--output-dir", default="",
                   help="Override output directory for generated files")
    p.add_argument("--no-report",  action="store_true",
                   help="Skip Word report generation")
    return p.parse_args()


def _parse_years(raw: str) -> Optional[List[int]]:
    if not raw.strip():
        return None
    try:
        return [int(y.strip()) for y in raw.split(",") if y.strip()]
    except ValueError:
        print(
            "ERROR: --years must be comma-separated integers, e.g. '2022,2023,2024'",
            file=sys.stderr,
        )
        sys.exit(1)


def main() -> None:
    args       = _parse_args()
    input_path = args.input

    if not Path(input_path).exists():
        print(f"ERROR: Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    is_manual = input_path.endswith(".json")
    if not is_manual and not args.company:
        print("ERROR: --company is required for PDF input", file=sys.stderr)
        sys.exit(1)

    fiscal_years: List[int] = (
        _parse_years(args.years) or list(range(_DEFAULT_YEAR_START, _DEFAULT_YEAR_END))
    )

    t0 = time.time()
    print(f"\n{_DIVIDER}")
    print("  Financial Analysis AI")
    print(_DIVIDER)

    # ── Step 1: Extract ───────────────────────────────────────────────────────
    print("\n[1/3] Extracting financial statements…")
    from agents.extractor import extract_from_json, extract_from_pdf

    if is_manual:
        financial_data = extract_from_json(input_path)
    else:
        financial_data = extract_from_pdf(
            path=input_path,
            company_name=args.company,
            fiscal_years=fiscal_years,
            currency=args.currency,
            unit=args.unit,
        )

    print(f"    Company   : {financial_data.company_name}")
    print(f"    Years     : {', '.join(str(y) for y in financial_data.sorted_years())}")
    print(f"    Currency  : {financial_data.currency} ({financial_data.unit})")
    print(f"    Confidence: {financial_data.metadata.overall_confidence:.0%}")
    if financial_data.metadata.warnings:
        print(f"    Warnings  : {len(financial_data.metadata.warnings)}")
        for w in financial_data.metadata.warnings[:3]:
            print(f"      ⚠  {w}")

    # ── Step 2: AI Commentary + Word Report ───────────────────────────────────
    if not args.no_report:
        print("\n[2/3] Generating AI commentary & Word report…")
        from agents.analyzer import generate_commentary
        from agents.report_generator import generate_report

        commentary  = generate_commentary(financial_data)
        report_path = generate_report(financial_data, commentary)
        print(f"    Report    : {report_path}")
    else:
        print("\n[2/3] Skipping Word report (--no-report).")
        commentary  = {}
        report_path = ""

    # ── Step 3: AI Next Steps ─────────────────────────────────────────────────
    print("\n[3/3] Generating AI next steps…")
    from agents.analyzer import generate_next_steps

    next_steps = generate_next_steps(financial_data, commentary)
    print(f"\n  AI-suggested next steps ({len(next_steps)}):")
    for step in next_steps:
        priority = step.get("priority", "").upper().ljust(6)
        print(f"    [{priority}] {step.get('title', '')}")
        print(f"             {step.get('description', '')}")

    # ── Done ──────────────────────────────────────────────────────────────────
    elapsed = time.time() - t0
    print(f"\n{_DIVIDER}")
    print(f"  Done in {elapsed:.1f}s")
    if report_path:
        print(f"  Report → {report_path}")
    print(_DIVIDER + "\n")


if __name__ == "__main__":
    main()
