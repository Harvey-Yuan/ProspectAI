"""Shared fixtures for Browser Agent tests."""

import os
import json

import pytest
from state import RawLead, EnrichedLead, SalesWorkflowState


# ── Test data (first row of dataAgent/leads.csv) ─────────────────────────────

COMPANY_NAME = "COBRE CERRILLOS S A COCESA"
COUNTRY = "Chile"
HS_CODE = "8544491090"
PRODUCT = "CONDUCTOR"

# Static JSON for pure-function unit tests only
SAMPLE_ENRICHED_JSON = json.dumps({
    "company_name": COMPANY_NAME,
    "contact_name": "Juan Pérez",
    "email": "contacto@cocesa.cl",
    "phone": "+56 2 2345 6789",
    "contact_form_url": None,
    "company_description": "Chilean copper wire and cable manufacturer",
    "source_url": "https://www.cocesa.cl/contacto",
})


@pytest.fixture
def raw_lead() -> RawLead:
    return RawLead(
        company_name=COMPANY_NAME,
        country=COUNTRY,
        hs_code=HS_CODE,
        product=PRODUCT,
    )


@pytest.fixture
def sample_enriched_lead() -> EnrichedLead:
    return EnrichedLead(
        company_name=COMPANY_NAME,
        contact_name="Juan Pérez",
        email="contacto@cocesa.cl",
        phone="+56 2 2345 6789",
        contact_form_url=None,
        company_description="Chilean copper wire and cable manufacturer",
        source_url="https://www.cocesa.cl/contacto",
    )


@pytest.fixture
def workflow_state(raw_lead: RawLead) -> SalesWorkflowState:
    return SalesWorkflowState(
        thread_id="test-thread-001",
        gmail_token=None,
        company_profile=None,
        search_params=None,
        raw_leads=[raw_lead],
        leads_csv_path=None,
        enriched_leads=None,
        enriched_csv_path=None,
        human_approved=False,
        approved_leads=None,
        activity_log=None,
        current_step="leads_validated",
        error_message=None,
        messages=[],
    )


def has_api_key() -> bool:
    """Check if InsForge API key is configured."""
    from dotenv import load_dotenv
    load_dotenv()
    return bool(os.getenv("INSFORGE_ANON_KEY"))


requires_api = pytest.mark.skipif(
    not has_api_key(),
    reason="INSFORGE_ANON_KEY not set — skip real LLM/browser tests",
)
