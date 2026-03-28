"""
Browser Agent — Contact Enrichment via Playwright MCP
======================================================
Uses Claude 4.5 Sonnet + @playwright/mcp to browse the web and extract
contact information for prospect companies.

MVP: only enriches the first company from raw_leads.
Set MVP_FIRST_ONLY = False to process all companies.
"""

import asyncio
import csv
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, List

import sse_manager
from llm_client import chat
from state import SalesWorkflowState, RawLead, EnrichedLead
from browserAgent.mcp_client import PlaywrightMCPClient
from browserAgent.prompts import (
    SYSTEM_PROMPT,
    WRAPUP_PROMPT,
    build_user_message,
    mcp_tools_to_llm_tools,
)

log = logging.getLogger("browserAgent")

OUTPUT_DIR = Path(__file__).parent.parent / "output"
MAX_ITERATIONS = 25
MVP_FIRST_ONLY = True


def _emit(state_or_thread_id: SalesWorkflowState | str | None, **kwargs) -> None:
    """Emit SSE event, accepting either a state dict or raw thread_id."""
    if isinstance(state_or_thread_id, dict):
        tid = state_or_thread_id.get("thread_id")
    else:
        tid = state_or_thread_id
    sse_manager.emit(tid, {"agent": "browserAgent", **kwargs})


# ── JSON Parsing & Validation ────────────────────────────────────────────────

def parse_enriched_lead(content: str) -> dict[str, Any] | None:
    """Extract a JSON object from LLM response, tolerating markdown fences."""
    content = content.strip()
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return None


def validate_enriched_lead(data: dict[str, Any] | None) -> EnrichedLead | None:
    """Validate parsed JSON against EnrichedLead requirements."""
    if not data:
        return None
    company_name = (data.get("company_name") or "").strip()
    contact_name = (data.get("contact_name") or "").strip()
    if not company_name or not contact_name:
        return None
    email = (data.get("email") or "").strip() or None
    phone = (data.get("phone") or "").strip() or None
    contact_form_url = (data.get("contact_form_url") or "").strip() or None
    if not any([email, phone, contact_form_url]):
        return None
    return EnrichedLead(
        company_name=company_name,
        contact_name=contact_name,
        email=email,
        phone=phone,
        contact_form_url=contact_form_url,
        company_description=(data.get("company_description") or "").strip() or None,
        source_url=(data.get("source_url") or "").strip() or None,
    )


# ── Agentic Loop ─────────────────────────────────────────────────────────────

async def _async_search(lead: RawLead, thread_id: str | None) -> EnrichedLead | None:
    """Run the LLM + Playwright MCP agentic loop for a single company."""
    company = lead["company_name"]
    client = PlaywrightMCPClient()
    try:
        log.info("[MCP] Starting Playwright MCP server...")
        await client.start()
        mcp_tools = await client.list_tools()
        llm_tools = mcp_tools_to_llm_tools(mcp_tools)
        log.info("[MCP] Ready — %d tools: %s", len(mcp_tools),
                 ", ".join(t["name"] for t in mcp_tools))

        system = SYSTEM_PROMPT.format(
            company_name=lead["company_name"],
            country=lead.get("country", ""),
        )
        user_msg = build_user_message(
            company_name=lead["company_name"],
            country=lead.get("country", ""),
            hs_code=lead.get("hs_code"),
            product=lead.get("product"),
        )
        messages: list[dict[str, Any]] = [{"role": "user", "content": user_msg}]

        for iteration in range(MAX_ITERATIONS):
            log.info("[LLM] iteration %d/%d — calling Claude...", iteration + 1, MAX_ITERATIONS)
            response = chat(
                messages=messages,
                system_prompt=system,
                tools=llm_tools,
                temperature=0.1,
            )

            if not response.tool_calls:
                log.info("[LLM] Final answer (no tool calls):\n%s", response.content[:500])
                parsed = parse_enriched_lead(response.content)
                result = validate_enriched_lead(parsed)
                if result:
                    log.info("[RESULT] Enriched: %s — email=%s, phone=%s",
                             result["company_name"], result.get("email"), result.get("phone"))
                    _emit(thread_id, type="agent_action", action="result",
                          message=f"Enriched: {result['company_name']} — {result.get('email') or 'no email'}")
                else:
                    log.warning("[RESULT] LLM returned text but validation failed")
                return result

            # Process tool calls (OpenAI format from InsForge API)
            messages.append({
                "role": "assistant",
                "content": response.content or "",
                "tool_calls": response.tool_calls,
            })

            for tc in response.tool_calls:
                func = tc.get("function") or {}
                tool_name = func.get("name") or tc.get("name", "")
                raw_args = func.get("arguments") or tc.get("input") or "{}"
                tool_input = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                tool_id = tc.get("id", "")

                log.info("[MCP] >>> %s(%s)", tool_name, json.dumps(tool_input, default=str)[:200])
                _emit(thread_id, type="agent_action", action=tool_name,
                      message=f"Tool: {tool_name}({json.dumps(tool_input, default=str)[:120]})")

                try:
                    tool_result = await client.call_tool(tool_name, tool_input)
                except Exception as e:
                    tool_result = f"Error: {e}"

                log.info("[MCP] <<< %s result (%d chars): %s",
                         tool_name, len(tool_result), tool_result[:300])

                if len(tool_result) > 8000:
                    tool_result = tool_result[:8000] + "\n...[truncated]"

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_id,
                    "content": tool_result,
                })

        # Force a final wrap-up call without tools
        log.info("[LLM] Reached %d iterations — sending wrap-up prompt...", MAX_ITERATIONS)
        _emit(thread_id, type="agent_action", action="wrapup",
              message=f"Reached {MAX_ITERATIONS} iterations — forcing final answer")
        try:
            messages.append({"role": "user", "content": WRAPUP_PROMPT})
            wrapup = chat(messages=messages, system_prompt=system, tools=None, temperature=0.1)
            log.info("[LLM] Wrap-up response:\n%s", wrapup.content[:500])
            parsed = parse_enriched_lead(wrapup.content)
            result = validate_enriched_lead(parsed)
            if result:
                log.info("[RESULT] Enriched (wrapup): %s", result["company_name"])
                _emit(thread_id, type="agent_action", action="result",
                      message=f"Enriched (wrapup): {result['company_name']}")
                return result
        except Exception as exc:
            log.error("[LLM] Wrap-up failed: %s", exc)

        _emit(thread_id, type="agent_action", action="max_iterations",
              message=f"Reached {MAX_ITERATIONS} iterations without final answer")
        return None

    except Exception as e:
        log.error("[ERROR] Enrichment failed for %s: %s", company, e, exc_info=True)
        _emit(thread_id, type="agent_status", status="running",
              message=f"Error during enrichment: {e}")
        return None
    finally:
        await client.close()
        log.info("[MCP] Server closed.")


def search_and_enrich_company(lead: RawLead, thread_id: str | None = None) -> EnrichedLead | None:
    """Sync entry point — runs the async agentic loop."""
    return asyncio.run(_async_search(lead, thread_id))


# ── CSV Persistence ──────────────────────────────────────────────────────────

def save_enriched_csv(leads: List[EnrichedLead]) -> str:
    """Write enriched leads to a timestamped CSV, return the path."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = OUTPUT_DIR / f"enriched_leads_{ts}.csv"
    fieldnames = [
        "company_name", "contact_name", "email",
        "phone", "contact_form_url", "company_description", "source_url",
    ]
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(leads)
    return str(csv_path)


# ── LangGraph Node ───────────────────────────────────────────────────────────

def enrich_leads(state: SalesWorkflowState) -> SalesWorkflowState:
    """LangGraph node — Browser Agent entry point."""
    raw_leads: List[RawLead] = state.get("raw_leads") or []

    if not raw_leads:
        _emit(state, type="agent_status", status="error",
              message="No raw leads to enrich.")
        return {**state, "current_step": "error", "error_message": "No raw leads to enrich."}

    # MVP: only first company; flip MVP_FIRST_ONLY to False for all
    leads_to_process = raw_leads[:1] if MVP_FIRST_ONLY else raw_leads
    total = len(leads_to_process)

    _emit(state, type="agent_status", status="running",
          message=f"Starting browser enrichment — {total} lead(s) to process...")

    thread_id = state.get("thread_id")
    enriched: List[EnrichedLead] = []

    for i, lead in enumerate(leads_to_process, 1):
        company = lead["company_name"]
        country = lead.get("country", "")
        _emit(state, type="agent_status", status="running",
              message=f"({i}/{total}) Searching: {company} ({country})")
        try:
            result = search_and_enrich_company(lead, thread_id)
            if result:
                enriched.append(result)
                _emit(state, type="agent_status", status="running",
                      message=f"({i}/{total}) Found contact for {company}")
            else:
                _emit(state, type="agent_status", status="running",
                      message=f"({i}/{total}) No contact found for {company}")
        except Exception as e:
            _emit(state, type="agent_status", status="running",
                  message=f"({i}/{total}) Error enriching {company}: {e}")

    csv_path = save_enriched_csv(enriched)

    _emit(state, type="agent_status", status="done",
          message=f"Enrichment complete: {len(enriched)}/{total} contacts found.")

    return {
        **state,
        "enriched_leads": enriched,
        "enriched_csv_path": csv_path,
        "current_step": "enrichment_done",
    }
