"""
AI Sales Multi-Agent System - LangGraph Workflow
=================================================

All sub-agents are only invoked through edges controlled by the Master Agent.
Master Agent validates each sub-agent's output before dispatching the next one.

Node flow:
  parse_company_profile     (master)
        |
  build_search_params       (master)  <-- dispatches Data Agent
        |
  data_agent
        |
  master_validate_leads     (master)  <-- validates; dispatches Browser Agent
        |
  browser_agent
        |
  master_validate_enrichment (master) <-- validates
        |
  -- interrupt_before -------------- Human-in-the-Loop checkpoint
        |
  human_review              (master passthrough, runs after approval)
        |
  crm_agent
        |
  review_activity_log       (master)  <-- final report
        |
  END
"""

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from state import SalesWorkflowState
from masterAgent.agent import (
    parse_company_profile,
    build_search_params,
    master_validate_leads,
    master_validate_enrichment,
    human_review_passthrough,
    review_activity_log,
)
from dataAgent.agent import fetch_leads
from browserAgent.agent import enrich_leads
from crmAgent.agent import send_outreach


# ── Error terminal node ──────────────────────────────────────────────────────

def error_end(state: SalesWorkflowState) -> SalesWorkflowState:
    import sse_manager
    sse_manager.emit(state.get("thread_id"), {
        "agent": "masterAgent",
        "type": "agent_status",
        "status": "error",
        "message": f"Workflow terminated: {state.get('error_message', 'unknown error')}",
    })
    return {**state, "current_step": "error"}


# ── Conditional routing helpers ──────────────────────────────────────────────

def _ok(state: SalesWorkflowState) -> str:
    return "error_end" if state.get("error_message") else "continue"


def route_after_profile(state: SalesWorkflowState) -> str:
    return "error_end" if state.get("error_message") else "build_search_params"


def route_after_validate_leads(state: SalesWorkflowState) -> str:
    return "error_end" if state.get("error_message") else "browser_agent"


def route_after_validate_enrichment(state: SalesWorkflowState) -> str:
    return "error_end" if state.get("error_message") else "human_review"


def route_after_human_review(state: SalesWorkflowState) -> str:
    return "error_end" if state.get("error_message") else "crm_agent"


def route_after_crm(state: SalesWorkflowState) -> str:
    return "error_end" if state.get("error_message") else "review_activity_log"


# ── Build and compile the graph ──────────────────────────────────────────────

def build_graph() -> StateGraph:
    builder = StateGraph(SalesWorkflowState)

    # Master Agent nodes
    builder.add_node("parse_company_profile", parse_company_profile)
    builder.add_node("build_search_params", build_search_params)
    builder.add_node("master_validate_leads", master_validate_leads)
    builder.add_node("master_validate_enrichment", master_validate_enrichment)
    builder.add_node("human_review", human_review_passthrough)
    builder.add_node("review_activity_log", review_activity_log)

    # Sub-agent nodes (only reachable through master-controlled edges)
    builder.add_node("data_agent", fetch_leads)
    builder.add_node("browser_agent", enrich_leads)
    builder.add_node("crm_agent", send_outreach)

    builder.add_node("error_end", error_end)

    # Entry point
    builder.set_entry_point("parse_company_profile")

    # Edges — each sub-agent is bracketed by master validation steps
    builder.add_conditional_edges(
        "parse_company_profile", route_after_profile,
        {"build_search_params": "build_search_params", "error_end": "error_end"},
    )
    builder.add_edge("build_search_params", "data_agent")
    builder.add_edge("data_agent", "master_validate_leads")
    builder.add_conditional_edges(
        "master_validate_leads", route_after_validate_leads,
        {"browser_agent": "browser_agent", "error_end": "error_end"},
    )
    builder.add_edge("browser_agent", "master_validate_enrichment")
    builder.add_conditional_edges(
        "master_validate_enrichment", route_after_validate_enrichment,
        {"human_review": "human_review", "error_end": "error_end"},
    )
    builder.add_conditional_edges(
        "human_review", route_after_human_review,
        {"crm_agent": "crm_agent", "error_end": "error_end"},
    )
    builder.add_conditional_edges(
        "crm_agent", route_after_crm,
        {"review_activity_log": "review_activity_log", "error_end": "error_end"},
    )
    builder.add_edge("review_activity_log", END)
    builder.add_edge("error_end", END)

    # MemorySaver enables Human-in-the-Loop state persistence across interrupts
    checkpointer = MemorySaver()
    return builder.compile(
        checkpointer=checkpointer,
        interrupt_before=["human_review"],
    )


graph = build_graph()
