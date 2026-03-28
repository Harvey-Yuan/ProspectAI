"""
Browser Agent — Contact Enrichment
====================================
For each raw lead (company_name + country) this agent:
  Step A: searches the web, visits the company website / LinkedIn /
          business directories, and extracts contact info.
  Step B (v1.1): heuristic discovery of similar companies.

Dependencies (to be installed):
    playwright, browser-use, langchain, langchain-openai
"""

import csv
import os
from datetime import datetime
from pathlib import Path
from typing import List

from state import SalesWorkflowState, RawLead, EnrichedLead

OUTPUT_DIR = Path(__file__).parent.parent / "output"


def _search_and_enrich_company(lead: RawLead) -> EnrichedLead | None:
    """
    TODO: implement using Playwright + browser-use + GPT-4o.

    Search strategy:
      1. DuckDuckGo / Google: "{company_name} contact email"
      2. Visit company homepage → scrape contact page
      3. LinkedIn company page → find decision-maker
      4. B2B directories (Kompass, Alibaba, etc.)

    Returns None if minimum required fields cannot be populated.
    """
    raise NotImplementedError("Browser Agent Step A not yet implemented")


def _save_enriched_csv(leads: List[EnrichedLead]) -> str:
    """Persist enriched leads to a CSV file and return the path."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = OUTPUT_DIR / f"enriched_leads_{timestamp}.csv"

    fieldnames = [
        "company_name", "contact_name", "email",
        "phone", "contact_form_url", "company_description", "source_url",
    ]
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(leads)

    return str(csv_path)


def enrich_leads(state: SalesWorkflowState) -> SalesWorkflowState:
    """
    LangGraph node — Browser Agent entry point.
    Iterates over raw_leads and enriches each one.
    """
    raw_leads: List[RawLead] = state.get("raw_leads") or []
    if not raw_leads:
        return {
            **state,
            "current_step": "error",
            "error_message": "No raw leads to enrich.",
        }

    print(f"[BrowserAgent] Enriching {len(raw_leads)} leads...")

    enriched: List[EnrichedLead] = []
    for i, lead in enumerate(raw_leads, 1):
        print(f"[BrowserAgent] ({i}/{len(raw_leads)}) {lead['company_name']}")
        try:
            result = _search_and_enrich_company(lead)
            if result:
                enriched.append(result)
        except NotImplementedError:
            # Placeholder until real implementation is added
            pass
        except Exception as e:
            print(f"[BrowserAgent] Error enriching {lead['company_name']}: {e}")

    if not enriched:
        # Return empty state — Human-in-the-Loop will still be triggered
        print("[BrowserAgent] Warning: no leads successfully enriched.")

    csv_path = _save_enriched_csv(enriched)
    print(f"[BrowserAgent] Saved enriched CSV → {csv_path}")

    return {
        **state,
        "enriched_leads": enriched,
        "enriched_csv_path": csv_path,
        "current_step": "enrichment_done",
    }
