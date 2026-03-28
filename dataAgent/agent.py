"""
Data Agent — Lead Source (Dummy / Skill Mode)
============================================
MVP behaviour: ignores all search parameters and always returns every CSV
file found under the dataAgent/ directory as raw leads.

Real v1 implementation would query ImportYeti / Panjiva / customs APIs.
"""

import os
import glob
import pandas as pd
from pathlib import Path
from typing import List

from state import SalesWorkflowState, RawLead

# Absolute path to the data directory — always reads from here regardless of
# what search parameters the Master Agent provides.
DATA_DIR = Path(__file__).parent.resolve()


def _discover_csv_files() -> List[Path]:
    """Return all CSV files inside DATA_DIR."""
    return sorted(DATA_DIR.glob("*.csv"))


def _csv_to_raw_leads(csv_path: Path) -> List[RawLead]:
    """
    Parse a trade-data CSV into a list of RawLead dicts.
    Column mapping is based on the leads.csv schema generated from test.xlsx.
    """
    df = pd.read_csv(csv_path, encoding="utf-8-sig")

    leads: List[RawLead] = []
    for _, row in df.iterrows():
        # Exporter is the prospective outreach target (seller/supplier side)
        company_name = str(row.get("出口商名称(标准)", "") or "").strip()
        country = str(row.get("原产国", "") or "").strip()
        hs_code = str(row.get("海关编码", "") or "").strip()
        product = str(row.get("产品(英文)", "") or "").strip()

        if not company_name:
            continue

        leads.append(
            RawLead(
                company_name=company_name,
                country=country,
                hs_code=hs_code or None,
                product=product or None,
            )
        )

    # Deduplicate by company_name
    seen = set()
    unique_leads: List[RawLead] = []
    for lead in leads:
        key = lead["company_name"].upper()
        if key not in seen:
            seen.add(key)
            unique_leads.append(lead)

    return unique_leads


def fetch_leads(state: SalesWorkflowState) -> SalesWorkflowState:
    """
    LangGraph node — Data Agent entry point.

    Dummy behaviour: scans DATA_DIR for CSV files and returns all unique
    exporter records as RawLead objects.  search_params is intentionally
    ignored in the MVP.
    """
    print(f"[DataAgent] Scanning for CSV files in: {DATA_DIR}")

    csv_files = _discover_csv_files()
    if not csv_files:
        return {
            **state,
            "current_step": "error",
            "error_message": f"No CSV files found in {DATA_DIR}",
        }

    all_leads: List[RawLead] = []
    primary_csv = str(csv_files[0])

    for csv_path in csv_files:
        leads = _csv_to_raw_leads(csv_path)
        print(f"[DataAgent] {csv_path.name}: {len(leads)} unique leads")
        all_leads.extend(leads)

    print(f"[DataAgent] Total raw leads: {len(all_leads)}")

    return {
        **state,
        "raw_leads": all_leads,
        "leads_csv_path": primary_csv,
        "current_step": "leads_fetched",
    }
