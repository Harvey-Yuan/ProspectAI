"""
Data Agent - Lead Source (Dummy / Skill Mode)
=============================================
MVP behaviour: ignores all search parameters and always returns every CSV
file found under the dataAgent/ directory as raw leads.

Real v1 implementation would query ImportYeti / Panjiva / customs APIs.
"""

from pathlib import Path
from typing import List

import pandas as pd

import sse_manager
from state import SalesWorkflowState, RawLead

# Absolute path to the data directory — always reads from here regardless of
# what search parameters the Master Agent provides.
DATA_DIR = Path(__file__).parent.resolve()


def _emit(state: SalesWorkflowState, **kwargs) -> None:
    sse_manager.emit(state.get("thread_id"), {"agent": "dataAgent", **kwargs})


def _discover_csv_files() -> List[Path]:
    return sorted(DATA_DIR.glob("*.csv"))


def _csv_to_raw_leads(csv_path: Path) -> List[RawLead]:
    """Parse a trade-data CSV into a list of RawLead dicts."""
    df = pd.read_csv(csv_path, encoding="utf-8-sig")

    leads: List[RawLead] = []
    for _, row in df.iterrows():
        # Exporter is the prospective outreach target
        company_name = str(row.get("出口商名称(标准)", "") or "").strip()
        country = str(row.get("原产国", "") or "").strip()
        hs_code = str(row.get("海关编码", "") or "").strip()
        product = str(row.get("产品(英文)", "") or "").strip()
        if not company_name:
            continue
        leads.append(RawLead(
            company_name=company_name,
            country=country,
            hs_code=hs_code or None,
            product=product or None,
        ))

    # Deduplicate by company_name
    seen: set = set()
    unique: List[RawLead] = []
    for lead in leads:
        key = lead["company_name"].upper()
        if key not in seen:
            seen.add(key)
            unique.append(lead)
    return unique


def fetch_leads(state: SalesWorkflowState) -> SalesWorkflowState:
    """
    LangGraph node - Data Agent entry point.
    Dummy mode: ignores search_params, always reads from DATA_DIR/*.csv.
    """
    _emit(state, type="agent_status", status="running",
          message=f"Scanning local trade data directory: {DATA_DIR.name}/")

    csv_files = _discover_csv_files()
    if not csv_files:
        _emit(state, type="agent_status", status="error",
              message=f"No CSV files found in {DATA_DIR}")
        return {
            **state,
            "current_step": "error",
            "error_message": f"No CSV files found in {DATA_DIR}",
        }

    all_leads: List[RawLead] = []
    for csv_path in csv_files:
        leads = _csv_to_raw_leads(csv_path)
        _emit(state, type="agent_status", status="running",
              message=f"Loaded {csv_path.name}: {len(leads)} unique exporter records")
        all_leads.extend(leads)

    _emit(state, type="agent_status", status="done",
          message=f"Done — {len(all_leads)} unique company leads ready for enrichment.")

    return {
        **state,
        "raw_leads": all_leads,
        "leads_csv_path": str(csv_files[0]),
        "current_step": "leads_fetched",
    }
