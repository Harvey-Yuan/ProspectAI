"""
AI Sales Multi-Agent System — Entry Point
==========================================
Demonstrates the full workflow using the dummy Data Agent and placeholder
Browser / CRM agents.

Usage:
    python main.py
"""

import uuid
from graph import graph
from state import SalesWorkflowState, CompanyProfile

SAMPLE_PROFILE: CompanyProfile = {
    "company_name": "Acme Wire & Cable Co.",
    "products": "Electrical conductors, copper cables, LSZH cables",
    "target_segment": "Industrial manufacturers, construction companies, mining operators",
    "description": "We supply high-quality electrical conductors certified to IEC and UL standards with 20+ years of manufacturing experience.",
    "ai_persona_name": "Alex from Acme",
    "sender_email": "alex@acmewire.example.com",
}

INITIAL_STATE: SalesWorkflowState = {
    "company_profile": SAMPLE_PROFILE,
    "search_params": None,
    "raw_leads": None,
    "leads_csv_path": None,
    "enriched_leads": None,
    "enriched_csv_path": None,
    "human_approved": False,
    "approved_leads": None,
    "activity_log": None,
    "current_step": "init",
    "error_message": None,
    "messages": [],
}


def run_workflow():
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    print("=" * 60)
    print("  AI Sales Multi-Agent System — Starting Campaign")
    print("=" * 60)

    # ── Phase 1: run until Human-in-the-Loop interrupt ──────────
    print("\n[Main] Phase 1: fetching & enriching leads...\n")
    for event in graph.stream(INITIAL_STATE, config=config):
        node_name = list(event.keys())[0]
        step = event[node_name].get("current_step", "")
        print(f"  ✓ {node_name} → {step}")

    # ── Phase 2: simulate human approval ────────────────────────
    print("\n[Main] Phase 2: simulating human approval (Human-in-the-Loop)\n")
    snapshot = graph.get_state(config)
    enriched = snapshot.values.get("enriched_leads") or []
    print(f"  Enriched leads available for review: {len(enriched)}")
    print("  (In production, user edits the enriched CSV in the UI then clicks Approve)")

    # Resume graph with approval
    graph.update_state(
        config,
        {"human_approved": True, "approved_leads": enriched},
    )

    # ── Phase 3: run CRM agent ───────────────────────────────────
    print("\n[Main] Phase 3: outreach execution...\n")
    for event in graph.stream(None, config=config):
        node_name = list(event.keys())[0]
        step = event[node_name].get("current_step", "")
        print(f"  ✓ {node_name} → {step}")

    # ── Final state ──────────────────────────────────────────────
    final = graph.get_state(config)
    log = final.values.get("activity_log") or []
    print(f"\n[Main] Campaign complete. Activity log entries: {len(log)}")
    print("=" * 60)


if __name__ == "__main__":
    run_workflow()
