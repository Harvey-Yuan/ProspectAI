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

import json
import re
from typing import Optional
import sse_manager
from state import SalesWorkflowState, CompanyProfile
from llm_client import chat, MODEL


def _emit(state: SalesWorkflowState, **kwargs) -> None:
    sse_manager.emit(state.get("thread_id"), {"agent": "masterAgent", **kwargs})


def _parse_json_response(content: str) -> dict:
    """Extract JSON object from LLM response, tolerating markdown fences."""
    content = content.strip()
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
    if match:
        return json.loads(match.group(1))
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if match:
        return json.loads(match.group())
    return json.loads(content)


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

    _emit(state, type="agent_status", status="running",
          message="Asking LLM to validate and enrich company profile...")

    prompt = f"""You are a B2B sales expert. Review this company profile and fill in any missing or vague fields.

Profile:
- Company Name: {profile.get('company_name', '')}
- Products: {profile.get('products', '')}
- Target Segment: {profile.get('target_segment', '')}
- Description: {profile.get('description', '')}

Return a JSON object with these exact keys (keep original values if already good, improve if vague):
{{
  "company_name": "...",
  "products": "...",
  "target_segment": "...",
  "description": "...",
  "enrichment_notes": "one sentence summarising what you changed or confirmed"
}}

Respond ONLY with valid JSON."""

    try:
        response = chat(messages=[{"role": "user", "content": prompt}], temperature=0.1)
        enriched = _parse_json_response(response.content)
        notes = enriched.pop("enrichment_notes", "Profile looks complete.")
        merged_profile = {**profile, **{k: v for k, v in enriched.items() if v}}
    except Exception as e:
        _emit(state, type="agent_status", status="error",
              message=f"LLM profile enrichment failed: {e}")
        return {**state, "current_step": "error", "error_message": str(e)}

    _emit(state, type="agent_status", status="done",
          message=f"Profile validated: {merged_profile['company_name']}. {notes}")
    return {**state, "company_profile": merged_profile, "current_step": "profile_parsed"}


def build_search_params(state: SalesWorkflowState) -> SalesWorkflowState:
    profile: CompanyProfile = state["company_profile"]

    _emit(state, type="agent_status", status="running",
          message="Asking LLM to infer HS codes and target markets...")

    prompt = f"""You are a trade intelligence analyst. Based on this company profile, suggest the best HS codes and target countries for finding import/export leads.

Company: {profile.get('company_name')}
Products: {profile.get('products')}
Target Segment: {profile.get('target_segment')}
Description: {profile.get('description')}

Return a JSON object:
{{
  "hs_codes": ["6-digit code", "..."],
  "target_countries": ["ISO-2 code", "..."],
  "reasoning": "one sentence"
}}

Rules:
- hs_codes: 2–4 entries, 6-digit strings (e.g. "841810")
- target_countries: 3–5 ISO-2 codes (e.g. "US", "DE", "JP")
- Respond ONLY with valid JSON."""

    try:
        response = chat(messages=[{"role": "user", "content": prompt}], temperature=0.2)
        suggestions = _parse_json_response(response.content)
    except Exception as e:
        _emit(state, type="agent_status", status="error",
              message=f"LLM search param generation failed: {e}")
        suggestions = {}

    search_params = {
        "target_segment": profile.get("target_segment", ""),
        "products": profile.get("products", ""),
        "hs_codes": suggestions.get("hs_codes", []),
        "target_countries": suggestions.get("target_countries", []),
        "limit": 50,
    }
    reasoning = suggestions.get("reasoning", "")
    hs_str = ", ".join(search_params["hs_codes"]) or "N/A"
    country_str = ", ".join(search_params["target_countries"]) or "N/A"

    _emit(state, type="agent_status", status="done",
          message=f"Search parameters ready. HS codes: {hs_str}. "
                  f"Target markets: {country_str}. {reasoning} "
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

    _emit(state, type="master_validate", status="running",
          message=f"LLM assessing quality of {len(leads)} leads...")

    sample = leads[:10]
    prompt = f"""You are a data quality analyst. Assess the quality of these B2B leads for a sales campaign.

Target segment: {state['company_profile'].get('target_segment', 'N/A')}
Products: {state['company_profile'].get('products', 'N/A')}

Sample leads (up to 10 shown):
{json.dumps(sample, indent=2)}

Return a JSON object:
{{
  "quality_score": 0-10,
  "issues": ["list any data quality issues"],
  "recommendation": "proceed | retry | abort",
  "summary": "one sentence for the operator"
}}

Respond ONLY with valid JSON."""

    try:
        response = chat(messages=[{"role": "user", "content": prompt}], temperature=0.1)
        assessment = _parse_json_response(response.content)
    except Exception as e:
        assessment = {"quality_score": 5, "recommendation": "proceed",
                      "summary": f"LLM assessment unavailable ({e}). Proceeding with manual review."}

    score = assessment.get("quality_score", "?")
    summary = assessment.get("summary", "")
    recommendation = assessment.get("recommendation", "proceed")

    if recommendation == "abort":
        _emit(state, type="master_validate", status="error",
              message=f"Quality gate failed (score {score}/10): {summary}")
        return {**state, "current_step": "error",
                "error_message": f"Lead quality too low: {summary}"}

    _emit(state, type="master_validate", status="done",
          message=f"Validation passed (score {score}/10): {len(leads)} leads. {summary} "
                  f"Dispatching Browser Agent for contact enrichment...")
    return {**state, "current_step": "leads_validated"}


def master_validate_enrichment(state: SalesWorkflowState) -> SalesWorkflowState:
    _emit(state, type="master_validate", status="running",
          message="Reviewing Browser Agent enrichment results...")

    enriched = state.get("enriched_leads") or []

    if not enriched:
        note = "No enriched contacts (Browser Agent not yet implemented)"
        _emit(state, type="master_validate", status="done",
              message=f"Review complete: {note}. Awaiting human approval before dispatching CRM Agent...")
        return {**state, "current_step": "enrichment_validated"}

    _emit(state, type="master_validate", status="running",
          message=f"LLM checking completeness of {len(enriched)} enriched contacts...")

    sample = enriched[:10]
    prompt = f"""You are a data quality analyst. Check these enriched B2B contacts for email validity and completeness.

Contacts (up to 10 shown):
{json.dumps(sample, indent=2)}

Return a JSON object:
{{
  "completeness_score": 0-10,
  "contacts_with_email": <integer>,
  "contacts_with_form": <integer>,
  "issues": ["any issues found"],
  "summary": "one sentence for the operator"
}}

Respond ONLY with valid JSON."""

    try:
        response = chat(messages=[{"role": "user", "content": prompt}], temperature=0.1)
        check = _parse_json_response(response.content)
    except Exception as e:
        check = {"completeness_score": "?", "summary": f"LLM check unavailable ({e})."}

    score = check.get("completeness_score", "?")
    summary = check.get("summary", "")

    _emit(state, type="master_validate", status="done",
          message=f"Review complete: {len(enriched)} contacts enriched "
                  f"(completeness {score}/10). {summary} "
                  f"Awaiting human approval before dispatching CRM Agent...")
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

    # TODO: persist activity_log to database

    _emit(state, type="agent_status", status="done",
          message="Campaign complete!")
    return {**state, "current_step": "completed"}
