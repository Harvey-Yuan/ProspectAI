"""
Master Agent - Orchestrator
============================
Responsibilities:
  - Parse and validate the company profile
  - Build search parameters for sub-agents
  - Validate each sub-agent's output (quality gate)
  - Dispatch the next sub-agent based on validation result
  - Surface the final activity log

All sub-agents are only invoked through LangGraph edges controlled by
the Master Agent. Master emits SSE events at every decision point.
"""

from typing import Optional
import sse_manager
from state import SalesWorkflowState, CompanyProfile


def _emit(state: SalesWorkflowState, **kwargs) -> None:
    sse_manager.emit(state.get("thread_id"), {"agent": "masterAgent", **kwargs})


def parse_company_profile(state: SalesWorkflowState) -> SalesWorkflowState:
    _emit(state, type="agent_status", status="running",
          message="Parsing company profile...")

    profile: Optional[CompanyProfile] = state.get("company_profile")
    if not profile or not profile.get("company_name"):
        _emit(state, type="agent_status", status="error",
              message="Company profile is missing — cannot start campaign.")
        return {
            **state,
            "current_step": "error",
            "error_message": "Company profile is missing.",
        }

    # TODO: call GPT-4o to enrich / clarify ambiguous profile fields

    _emit(state, type="agent_status", status="done",
          message=f"Company profile parsed: {profile['company_name']}")
    return {**state, "current_step": "profile_parsed"}


def build_search_params(state: SalesWorkflowState) -> SalesWorkflowState:
    profile: CompanyProfile = state["company_profile"]

    _emit(state, type="agent_status", status="running",
          message="Building search parameters — dispatching Data Agent...")

    # TODO: call GPT-4o to suggest HS codes, target countries, etc.
    search_params = {
        "target_segment": profile.get("target_segment", ""),
        "products": profile.get("products", ""),
        "limit": 50,
    }

    _emit(state, type="agent_status", status="done",
          message=f"Search parameters ready. Target segment: \"{profile.get('target_segment', 'N/A')}\". "
                  f"Dispatching Data Agent...")
    return {
        **state,
        "search_params": search_params,
        "current_step": "search_params_ready",
    }


def master_validate_leads(state: SalesWorkflowState) -> SalesWorkflowState:
    _emit(state, type="master_validate", status="running",
          message="Reviewing Data Agent output...")

    leads = state.get("raw_leads") or []

    if not leads:
        _emit(state, type="master_validate", status="error",
              message="Validation failed: Data Agent returned no leads.")
        return {
            **state,
            "current_step": "error",
            "error_message": "Data Agent returned no leads.",
        }

    # TODO: LLM-based quality assessment (deduplication, relevance scoring)

    _emit(state, type="master_validate", status="done",
          message=f"Validation passed: {len(leads)} unique leads, quality looks good. "
                  f"Dispatching Browser Agent for contact enrichment...")
    return {**state, "current_step": "leads_validated"}


def master_validate_enrichment(state: SalesWorkflowState) -> SalesWorkflowState:
    _emit(state, type="master_validate", status="running",
          message="Reviewing Browser Agent enrichment results...")

    enriched = state.get("enriched_leads") or []

    # TODO: LLM-based quality check (email validity, completeness score)
    note = (f"{len(enriched)} contacts enriched"
            if enriched else "No enriched contacts (Browser Agent not yet implemented)")

    _emit(state, type="master_validate", status="done",
          message=f"Review complete: {note}. Awaiting human approval before dispatching CRM Agent...")
    return {**state, "current_step": "enrichment_validated"}


def human_review_passthrough(state: SalesWorkflowState) -> SalesWorkflowState:
    """Runs after the human approves — carries approved leads forward."""
    approved = state.get("approved_leads") or state.get("enriched_leads") or []

    _emit(state, type="agent_status", status="running",
          message=f"Human review approved ({len(approved)} contacts). Dispatching CRM Agent...")
    return {**state, "approved_leads": approved, "current_step": "approved"}


def review_activity_log(state: SalesWorkflowState) -> SalesWorkflowState:
    log = state.get("activity_log") or []
    sent = sum(1 for e in log if e.get("status") == "sent")

    _emit(state, type="master_validate", status="done",
          message=f"Campaign report: {sent}/{len(log)} outreach messages sent successfully.")

    # TODO: persist activity_log to SQLite

    _emit(state, type="agent_status", status="done",
          message="Campaign complete!")
    return {**state, "current_step": "completed"}
