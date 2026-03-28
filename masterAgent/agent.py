"""
Master Agent — AI Sales Orchestrator
Parses company profile and builds search parameters for downstream agents.
"""

from state import SalesWorkflowState, CompanyProfile


def parse_company_profile(state: SalesWorkflowState) -> SalesWorkflowState:
    """
    Entry node: validate and normalise the company profile provided by the user.
    In production this will also call an LLM to enrich / clarify the profile.
    """
    profile = state.get("company_profile")
    if not profile:
        return {
            **state,
            "current_step": "error",
            "error_message": "Company profile is missing.",
        }

    # TODO: call GPT-4o to extract / clarify ambiguous fields in the profile

    return {
        **state,
        "current_step": "profile_parsed",
    }


def build_search_params(state: SalesWorkflowState) -> SalesWorkflowState:
    """
    Derive Data Agent search parameters from the company profile.
    In production this will use an LLM to suggest HS codes, target countries, etc.
    """
    profile: CompanyProfile = state["company_profile"]

    # TODO: call GPT-4o to generate smart search parameters
    search_params = {
        "target_segment": profile.get("target_segment", ""),
        "products": profile.get("products", ""),
        "limit": 50,
    }

    return {
        **state,
        "search_params": search_params,
        "current_step": "search_params_ready",
    }


def review_activity_log(state: SalesWorkflowState) -> SalesWorkflowState:
    """
    Final node: surface the activity log after CRM Agent completes outreach.
    In production this persists the log to SQLite and notifies the user.
    """
    activity_log = state.get("activity_log", [])

    # TODO: persist activity_log to SQLite
    # TODO: push summary notification to frontend

    print(f"[MasterAgent] Campaign complete. {len(activity_log)} outreach attempts logged.")

    return {
        **state,
        "current_step": "completed",
    }
