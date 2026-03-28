"""
Browser Agent - Contact Enrichment
====================================
For each raw lead (company_name + country) this agent:
  Step A: searches the web, visits the company website / LinkedIn /
          business directories, and extracts contact info.
  Step B (v1.1): heuristic discovery of similar companies.

Dependencies (to be installed):
    playwright, browser-use, langchain-openai
"""

import csv
from datetime import datetime
from pathlib import Path
from typing import List

import sse_manager
from state import SalesWorkflowState, RawLead, EnrichedLead

OUTPUT_DIR = Path(__file__).parent.parent / "output"


def _emit(state: SalesWorkflowState, **kwargs) -> None:
    sse_manager.emit(state.get("thread_id"), {"agent": "browserAgent", **kwargs})


def _search_and_enrich_company(lead: RawLead) -> EnrichedLead | None:
    """
    TODO: implement using Playwright + browser-use + GPT-4o.

    Search strategy:
      1. DuckDuckGo / Google: "{company_name} contact email"
      2. Visit company homepage -> scrape contact page
      3. LinkedIn company page -> find decision-maker
      4. B2B directories (Kompass, Alibaba, etc.)

    Returns None if required fields cannot be populated.
    """
    raise NotImplementedError("Browser Agent Step A not yet implemented")


def _save_enriched_csv(leads: List[EnrichedLead]) -> str:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = OUTPUT_DIR / f"enriched_leads_{ts}.csv"
    fieldnames = ["company_name", "contact_name", "email",
                  "phone", "contact_form_url", "company_description", "source_url"]
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(leads)
    return str(csv_path)


def enrich_leads(state: SalesWorkflowState) -> SalesWorkflowState:
    """LangGraph node - Browser Agent entry point."""
    raw_leads: List[RawLead] = state.get("raw_leads") or []

    if not raw_leads:
        _emit(state, type="agent_status", status="error",
              message="No raw leads to enrich.")
        return {**state, "current_step": "error", "error_message": "No raw leads to enrich."}

    _emit(state, type="agent_status", status="running",
          message=f"Initialising browser — {len(raw_leads)} leads queued for enrichment...")

    enriched: List[EnrichedLead] = []
    for i, lead in enumerate(raw_leads, 1):
        _emit(state, type="agent_status", status="running",
              message=f"({i}/{len(raw_leads)}) Searching: {lead['company_name']} ({lead.get('country', '')})")
        try:
            result = _search_and_enrich_company(lead)
            if result:
                enriched.append(result)
        except NotImplementedError:
            pass  # placeholder until real implementation
        except Exception as e:
            _emit(state, type="agent_status", status="running",
                  message=f"Warning: enrichment failed for {lead['company_name']}: {e}")

    csv_path = _save_enriched_csv(enriched)

    _emit(state, type="agent_status", status="done",
          message=f"Enrichment done: {len(enriched)} contacts found "
                  f"(Browser Agent is a placeholder — not yet implemented).")

    return {
        **state,
        "enriched_leads": enriched,
        "enriched_csv_path": csv_path,
        "current_step": "enrichment_done",
    }
