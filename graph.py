"""
AI Sales Multi-Agent System — LangGraph Workflow
=================================================

Node map:
                         ┌─────────────────────────────────┐
                         │      parse_company_profile       │  ← entry
                         └──────────────┬──────────────────┘
                                        │
                         ┌──────────────▼──────────────────┐
                         │       build_search_params        │
                         └──────────────┬──────────────────┘
                                        │
                         ┌──────────────▼──────────────────┐
                         │    data_agent (fetch_leads)      │  ← dummy skill
                         └──────────────┬──────────────────┘
                                        │
                         ┌──────────────▼──────────────────┐
                         │  browser_agent (enrich_leads)    │
                         └──────────────┬──────────────────┘
                                        │
                         ┌──────────────▼──────────────────┐
                         │      human_review_checkpoint     │  ← interrupt
                         └──────────────┬──────────────────┘
                                   approved?
                              yes ──┘   └── no (loop back / abort)
                         ┌──────────────▼──────────────────┐
                         │    crm_agent (send_outreach)     │
                         └──────────────┬──────────────────┘
                                        │
                         ┌──────────────▼──────────────────┐
                         │      review_activity_log         │  ← end
                         └─────────────────────────────────┘
"""

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from state import SalesWorkflowState
from masterAgent.agent import parse_company_profile, build_search_params, review_activity_log
from dataAgent.agent import fetch_leads
from browserAgent.agent import enrich_leads
from crmAgent.agent import send_outreach


# ── Human-in-the-Loop node ──────────────────────────────────────────────────

def human_review_checkpoint(state: SalesWorkflowState) -> SalesWorkflowState:
    """
    Interrupt node: execution pauses here so the user can review and edit
    the enriched CSV before outreach begins.

    In production:
      - The frontend renders the enriched_leads table for editing.
      - The user clicks "Approve & Send".
      - The graph is resumed with human_approved=True and the
        (possibly edited) approved_leads list.

    For now the node simply copies enriched_leads → approved_leads when
    human_approved is already True (set externally before resuming).
    """
    if not state.get("human_approved"):
        # Graph will be interrupted here by LangGraph's interrupt mechanism.
        # The frontend resumes it by calling graph.update_state() with
        # human_approved=True and optionally a modified approved_leads list.
        return {
            **state,
            "current_step": "awaiting_approval",
        }

    # User has approved — carry enriched leads forward (they may have been
    # edited externally before the graph was resumed).
    approved = state.get("approved_leads") or state.get("enriched_leads") or []
    return {
        **state,
        "approved_leads": approved,
        "current_step": "approved",
    }


# ── Conditional edge functions ───────────────────────────────────────────────

def route_after_profile(state: SalesWorkflowState) -> str:
    if state.get("error_message"):
        return "error_end"
    return "build_search_params"


def route_after_data_agent(state: SalesWorkflowState) -> str:
    if state.get("error_message"):
        return "error_end"
    raw_leads = state.get("raw_leads") or []
    if not raw_leads:
        return "error_end"
    return "browser_agent"


def route_after_browser_agent(state: SalesWorkflowState) -> str:
    if state.get("error_message"):
        return "error_end"
    return "human_review"


def route_after_human_review(state: SalesWorkflowState) -> str:
    current = state.get("current_step")
    if current == "awaiting_approval":
        # Stay at this node until the graph is resumed externally.
        return "human_review"
    if state.get("error_message"):
        return "error_end"
    return "crm_agent"


def route_after_crm(state: SalesWorkflowState) -> str:
    if state.get("error_message"):
        return "error_end"
    return "review_activity_log"


# ── Error terminal node ──────────────────────────────────────────────────────

def error_end(state: SalesWorkflowState) -> SalesWorkflowState:
    print(f"[Graph] Workflow ended with error: {state.get('error_message')}")
    return {**state, "current_step": "error"}


# ── Build the graph ──────────────────────────────────────────────────────────

def build_graph() -> StateGraph:
    builder = StateGraph(SalesWorkflowState)

    # Register nodes
    builder.add_node("parse_company_profile", parse_company_profile)
    builder.add_node("build_search_params", build_search_params)
    builder.add_node("data_agent", fetch_leads)
    builder.add_node("browser_agent", enrich_leads)
    builder.add_node("human_review", human_review_checkpoint)
    builder.add_node("crm_agent", send_outreach)
    builder.add_node("review_activity_log", review_activity_log)
    builder.add_node("error_end", error_end)

    # Entry point
    builder.set_entry_point("parse_company_profile")

    # Edges
    builder.add_conditional_edges(
        "parse_company_profile",
        route_after_profile,
        {"build_search_params": "build_search_params", "error_end": "error_end"},
    )
    builder.add_edge("build_search_params", "data_agent")
    builder.add_conditional_edges(
        "data_agent",
        route_after_data_agent,
        {"browser_agent": "browser_agent", "error_end": "error_end"},
    )
    builder.add_conditional_edges(
        "browser_agent",
        route_after_browser_agent,
        {"human_review": "human_review", "error_end": "error_end"},
    )
    builder.add_conditional_edges(
        "human_review",
        route_after_human_review,
        {
            "human_review": "human_review",   # loop while awaiting approval
            "crm_agent": "crm_agent",
            "error_end": "error_end",
        },
    )
    builder.add_conditional_edges(
        "crm_agent",
        route_after_crm,
        {"review_activity_log": "review_activity_log", "error_end": "error_end"},
    )
    builder.add_edge("review_activity_log", END)
    builder.add_edge("error_end", END)

    # Persist state between steps (enables Human-in-the-Loop interrupts)
    checkpointer = MemorySaver()
    return builder.compile(
        checkpointer=checkpointer,
        interrupt_before=["human_review"],   # pause before showing enriched CSV
    )


# Exported compiled graph
graph = build_graph()
