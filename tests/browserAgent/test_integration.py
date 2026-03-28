"""
Integration tests for Browser Agent — REAL LLM + REAL Playwright MCP.
No mocks. Calls Claude 4.5 Sonnet via InsForge API and browses the web
with a headless Chromium instance via @playwright/mcp.

Each MCP call and its result is logged to stdout (run with ``pytest -s``).

Requires:
  - INSFORGE_ANON_KEY set in .env
  - Node.js + npx available on PATH
  - Network access

Skipped automatically if INSFORGE_ANON_KEY is not configured.
"""

import csv
import logging
from pathlib import Path
from unittest.mock import patch

import pytest

import sse_manager
from browserAgent.agent import search_and_enrich_company, enrich_leads
from state import RawLead, SalesWorkflowState
from tests.browserAgent.conftest import (
    COMPANY_NAME,
    COUNTRY,
    HS_CODE,
    PRODUCT,
    requires_api,
)

# ── Enable verbose agent logging during test run ─────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("browserAgent").setLevel(logging.INFO)


def _make_state(raw_leads: list[RawLead] | None = None,
                thread_id: str = "integration-real-001") -> SalesWorkflowState:
    return SalesWorkflowState(
        thread_id=thread_id,
        gmail_token=None,
        company_profile=None,
        search_params=None,
        raw_leads=raw_leads,
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


# ── Shared fixture: run the real agent ONCE, reuse across all tests ──────────

@pytest.fixture(scope="module")
def real_enrichment_result(tmp_path_factory):
    """
    Run the full enrich_leads() with real LLM + real Playwright MCP.
    Cached at module level so it only runs once for all tests.
    """
    from tests.browserAgent.conftest import has_api_key
    if not has_api_key():
        pytest.skip("INSFORGE_ANON_KEY not set")

    tmp = tmp_path_factory.mktemp("enrichment")
    thread_id = "integration-real-001"
    sse_manager.setup(thread_id)

    lead = RawLead(
        company_name=COMPANY_NAME,
        country=COUNTRY,
        hs_code=HS_CODE,
        product=PRODUCT,
    )
    state = _make_state(raw_leads=[lead], thread_id=thread_id)

    with patch("browserAgent.agent.OUTPUT_DIR", tmp):
        result_state = enrich_leads(state)

    # Collect SSE events
    q = sse_manager.get_sse_queue(thread_id)
    events = []
    while not q.empty():
        events.append(q.get_nowait())
    sse_manager.close(thread_id)

    return {
        "state": result_state,
        "events": events,
        "tmp_dir": tmp,
    }


# ── Tests ─────────────────────────────────────────────────────────────────────

@requires_api
class TestRealEnrichmentFlow:
    """
    All tests share a single real agent run (module-scoped fixture).
    Intermediate steps are printed via the browserAgent logger.
    """

    @pytest.mark.timeout(300)
    def test_agent_completed_without_error(self, real_enrichment_result):
        """The LangGraph node must complete with enrichment_done status."""
        st = real_enrichment_result["state"]
        assert st["current_step"] == "enrichment_done", (
            f"Expected enrichment_done, got {st['current_step']}: {st.get('error_message')}")
        assert st["error_message"] is None

    @pytest.mark.timeout(300)
    def test_enriched_lead_has_valid_schema(self, real_enrichment_result):
        """If the agent found data, verify the schema is correct."""
        st = real_enrichment_result["state"]
        enriched = st.get("enriched_leads") or []

        if len(enriched) == 0:
            # Agent couldn't find contact info — this is acceptable for niche companies.
            # Verify the agent at least attempted (via SSE events).
            events = real_enrichment_result["events"]
            action_events = [e for e in events if e.get("type") == "agent_action"]
            assert len(action_events) >= 3, (
                "Agent should have made at least 3 browser actions even if no result")
            print(f"\n  Agent made {len(action_events)} actions but found no contact info — OK for niche company")
            return

        lead = enriched[0]
        expected_keys = {
            "company_name", "contact_name", "email", "phone",
            "contact_form_url", "company_description", "source_url",
        }
        assert set(lead.keys()) == expected_keys

        assert lead["company_name"], "company_name must be non-empty"
        assert lead["contact_name"], "contact_name must be non-empty"
        assert any([
            lead.get("email"), lead.get("phone"), lead.get("contact_form_url"),
        ]), "At least one contact channel required"

        print(f"\n{'═'*60}")
        print(f"  ENRICHED RESULT for {COMPANY_NAME}")
        print(f"{'═'*60}")
        for k, v in lead.items():
            print(f"  {k}: {v}")
        print(f"{'═'*60}")

    @pytest.mark.timeout(300)
    def test_csv_file_is_created(self, real_enrichment_result):
        """A CSV file must always be created (even if empty)."""
        st = real_enrichment_result["state"]
        csv_path = st.get("enriched_csv_path")
        assert csv_path is not None, "enriched_csv_path is None"
        assert Path(csv_path).exists(), f"CSV not found at {csv_path}"

        with open(csv_path, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        enriched = st.get("enriched_leads") or []
        assert len(rows) == len(enriched), (
            f"CSV rows ({len(rows)}) must match enriched_leads ({len(enriched)})")

        if rows:
            assert rows[0]["company_name"], "CSV company_name is empty"
        print(f"\n  CSV: {csv_path} — {len(rows)} row(s)")

    @pytest.mark.timeout(300)
    def test_sse_events_contain_agent_actions(self, real_enrichment_result):
        """SSE events must include browser agent actions (MCP tool calls)."""
        events = real_enrichment_result["events"]
        assert len(events) >= 3, f"Expected ≥3 SSE events, got {len(events)}"

        agents = {e.get("agent") for e in events}
        assert "browserAgent" in agents

        action_events = [e for e in events if e.get("type") == "agent_action"]
        assert len(action_events) >= 1, "No agent_action events emitted"

        print(f"\n  SSE events: {len(events)} total, {len(action_events)} agent actions")
        print(f"  {'─'*56}")
        for e in events:
            status = e.get("status", e.get("action", ""))
            msg = e.get("message", "")[:90]
            print(f"  [{e.get('type'):14s}] {status:20s} {msg}")

    @pytest.mark.timeout(300)
    def test_browser_actually_navigated(self, real_enrichment_result):
        """Verify the agent actually used browser_navigate (real Playwright call)."""
        events = real_enrichment_result["events"]
        nav_events = [
            e for e in events
            if e.get("type") == "agent_action" and e.get("action") == "browser_navigate"
        ]
        assert len(nav_events) >= 1, "Agent never called browser_navigate"
        print(f"\n  browser_navigate calls: {len(nav_events)}")
        for e in nav_events:
            print(f"    → {e.get('message', '')[:100]}")

    @pytest.mark.timeout(300)
    def test_llm_was_called_multiple_times(self, real_enrichment_result):
        """The agentic loop must have called the LLM multiple times."""
        events = real_enrichment_result["events"]
        # Each MCP tool call = 1 LLM call. Plus start/end status events.
        action_events = [e for e in events if e.get("type") == "agent_action"]
        assert len(action_events) >= 2, (
            f"Expected ≥2 agent actions (LLM iterations), got {len(action_events)}")
        print(f"\n  LLM agentic iterations: {len(action_events)}")


# ── Edge cases (no API needed) ───────────────────────────────────────────────

class TestEnrichLeadsEmptyInput:
    def test_no_raw_leads_returns_error(self):
        state = _make_state(raw_leads=[])
        result = enrich_leads(state)
        assert result["current_step"] == "error"
        assert "No raw leads" in result["error_message"]

    def test_none_raw_leads_returns_error(self):
        state = _make_state(raw_leads=None)
        result = enrich_leads(state)
        assert result["current_step"] == "error"
