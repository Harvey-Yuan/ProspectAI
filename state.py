"""
Shared workflow state for the AI Sales Multi-Agent System.
Passed between all nodes in the LangGraph.
"""

from typing import TypedDict, Optional, List, Dict, Any, Annotated
import operator


class CompanyProfile(TypedDict):
    company_name: str
    products: str
    target_segment: str
    description: str
    ai_persona_name: str
    sender_email: str


class RawLead(TypedDict):
    company_name: str
    country: str
    hs_code: Optional[str]
    product: Optional[str]


class EnrichedLead(TypedDict):
    company_name: str
    contact_name: str
    email: Optional[str]
    phone: Optional[str]
    contact_form_url: Optional[str]
    company_description: Optional[str]
    source_url: Optional[str]


class ActivityEntry(TypedDict):
    company_name: str
    contact_name: str
    channel_used: str   # "email" | "form" | "phone"
    status: str         # "sent" | "failed" | "pending"
    timestamp: str
    email_preview: str


class SalesWorkflowState(TypedDict):
    # ── Runtime identity (used for SSE routing) ──────────────────
    thread_id: Optional[str]

    # ── Inputs ──────────────────────────────────────────────────
    company_profile: Optional[CompanyProfile]
    search_params: Optional[Dict[str, Any]]

    # ── Data Agent output ────────────────────────────────────────
    raw_leads: Optional[List[RawLead]]
    leads_csv_path: Optional[str]

    # ── Browser Agent output ─────────────────────────────────────
    enriched_leads: Optional[List[EnrichedLead]]
    enriched_csv_path: Optional[str]

    # ── Human-in-the-Loop ────────────────────────────────────────
    human_approved: bool
    approved_leads: Optional[List[EnrichedLead]]

    # ── CRM Agent output ─────────────────────────────────────────
    activity_log: Optional[List[ActivityEntry]]

    # ── Workflow control ─────────────────────────────────────────
    current_step: str        # e.g. "fetching_leads", "enriching", ...
    error_message: Optional[str]
    messages: Annotated[List[Dict[str, Any]], operator.add]  # LLM message history
