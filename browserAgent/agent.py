"""
Browser Agent - Contact Enrichment
====================================
Strategy per lead:
  1. DuckDuckGo: "{company_name} {country} contact email"
  2. Visit the top result URL (company homepage)
  3. LLM extracts: contact_name, email, phone, contact_form_url, description

Uses playwright.sync_api (runs in background thread — sync is fine).
Anti-detection techniques from reference project.
Screenshots are streamed to the frontend via SSE after each navigation.
"""

import base64
import csv
import json
import re
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import sse_manager
from llm_client import chat
from state import SalesWorkflowState, RawLead, EnrichedLead

OUTPUT_DIR = Path(__file__).parent.parent / "output"

MAX_LEADS   = 3
TIMEOUT_MS  = 15_000
SEARCH_WAIT = 8_000


# ── Helpers ────────────────────────────────────────────────────────────────────

def _emit(state: SalesWorkflowState, **kwargs) -> None:
    sse_manager.emit(state.get("thread_id"), {"agent": "browserAgent", **kwargs})


def _snap(page, state: SalesWorkflowState, label: str = "") -> None:
    """Take a JPEG screenshot and push it to the frontend via SSE."""
    try:
        data = page.screenshot(type="jpeg", quality=55, scale="css")
        b64  = base64.b64encode(data).decode()
        _emit(state,
              type="browser_screenshot",
              label=label,
              url=page.url,
              image=b64)
    except Exception:
        pass


def _make_browser_context(playwright):
    browser = playwright.chromium.launch(
        headless=True,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ],
    )
    context = browser.new_context(
        viewport={"width": 1366, "height": 900},
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        locale="en-US",
    )
    context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        delete window.__playwright;
        delete window.__pw_manual;
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
        Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
    """)
    return browser, context


def _safe_goto(page, url: str, timeout: int = TIMEOUT_MS) -> bool:
    try:
        resp = page.goto(url, timeout=timeout, wait_until="domcontentloaded")
        return resp is not None and resp.status < 400
    except Exception:
        return False


def _page_text(page, max_chars: int = 3000) -> str:
    try:
        return page.inner_text("body")[:max_chars]
    except Exception:
        return ""


# ── Search ─────────────────────────────────────────────────────────────────────

def _duckduckgo_search(page, company: str, country: str,
                       state: SalesWorkflowState) -> tuple[str, list[str]]:
    query = f'"{company}" {country} contact email'
    url   = f"https://duckduckgo.com/?q={urllib.parse.quote(query)}&ia=web"

    if not _safe_goto(page, url, timeout=20_000):
        return "", []

    try:
        page.wait_for_selector("[data-testid='result']", timeout=SEARCH_WAIT)
    except Exception:
        pass

    _snap(page, state, f"Search: {company}")

    text: str = _page_text(page, 4000)
    urls: list[str] = []
    try:
        for link in page.query_selector_all("a[data-testid='result-title-a']")[:5]:
            href = link.get_attribute("href") or ""
            if href.startswith("http") and "duckduckgo" not in href:
                urls.append(href)
    except Exception:
        pass

    return text, urls


# ── LLM extraction ─────────────────────────────────────────────────────────────

def _parse_json(text: str) -> dict:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        return json.loads(m.group())
    return json.loads(text)


def _llm_extract(company: str, country: str,
                 search_text: str, page_text: str,
                 source_url: str) -> dict:
    prompt = f"""You are a B2B data analyst. Extract contact information for this company from web content.

Company: {company}
Country: {country}

--- SEARCH RESULTS ---
{search_text[:2000]}

--- COMPANY PAGE ---
{page_text[:2000]}

Return ONLY a JSON object:
{{
  "contact_name": "Full name of procurement/import manager or CEO (or null)",
  "email": "Business email address (or null — must not be a personal gmail)",
  "phone": "Phone number with country code (or null)",
  "contact_form_url": "URL of a contact / inquiry form (or null)",
  "company_description": "One sentence describing what the company does",
  "source_url": "Most relevant URL from the content (or empty string)"
}}

Rules:
- Only include information explicitly found in the content above.
- contact_form_url: prefer /contact, /inquiry, /about pages over the homepage."""

    try:
        response = chat(messages=[{"role": "user", "content": prompt}], temperature=0.1)
        return _parse_json(response.content)
    except Exception:
        return {
            "contact_name": None, "email": None, "phone": None,
            "contact_form_url": source_url or None,
            "company_description": f"Import/export company based in {country}.",
            "source_url": source_url,
        }


# ── Per-lead enrichment ────────────────────────────────────────────────────────

def _enrich_one(lead: RawLead, page,
                state: SalesWorkflowState) -> Optional[EnrichedLead]:
    company = lead["company_name"]
    country = lead.get("country", "")

    search_text, result_urls = _duckduckgo_search(page, company, country, state)

    page_text  = ""
    source_url = ""
    for url in result_urls[:3]:
        if _safe_goto(page, url):
            page_text  = _page_text(page, 3000)
            source_url = url
            _snap(page, state, f"Homepage: {company}")
            if page_text.strip():
                try:
                    contact_url = url.rstrip("/") + "/contact"
                    if _safe_goto(page, contact_url, timeout=8_000):
                        extra = _page_text(page, 1500)
                        page_text += "\n\n[Contact page]\n" + extra
                        _snap(page, state, f"Contact page: {company}")
                except Exception:
                    pass
                break

    data = _llm_extract(company, country, search_text, page_text, source_url)

    return EnrichedLead(
        company_name=company,
        contact_name=data.get("contact_name") or "",
        email=data.get("email"),
        phone=data.get("phone"),
        contact_form_url=data.get("contact_form_url") or (source_url or None),
        company_description=data.get("company_description"),
        source_url=data.get("source_url") or source_url or None,
    )


# ── CSV helper ─────────────────────────────────────────────────────────────────

def _save_csv(leads: List[EnrichedLead]) -> str:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = OUTPUT_DIR / f"enriched_leads_{ts}.csv"
    fields   = ["company_name", "contact_name", "email",
                "phone", "contact_form_url", "company_description", "source_url"]
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(leads)
    return str(csv_path)


# ── LangGraph node ─────────────────────────────────────────────────────────────

def enrich_leads(state: SalesWorkflowState) -> SalesWorkflowState:
    """Browser Agent entry point — called by LangGraph."""
    from playwright.sync_api import sync_playwright

    raw_leads: List[RawLead] = state.get("raw_leads") or []
    if not raw_leads:
        _emit(state, type="agent_status", status="error",
              message="No raw leads to enrich.")
        return {**state, "current_step": "error", "error_message": "No raw leads to enrich."}

    to_process = raw_leads[:MAX_LEADS]
    _emit(state, type="agent_status", status="running",
          message=f"Launching browser — enriching {len(to_process)} leads "
                  f"(max {MAX_LEADS} per campaign)...")

    enriched: List[EnrichedLead] = []

    with sync_playwright() as pw:
        browser, context = _make_browser_context(pw)
        page = context.new_page()

        for i, lead in enumerate(to_process, 1):
            _emit(state, type="agent_status", status="running",
                  message=f"({i}/{len(to_process)}) Searching: "
                          f"{lead['company_name']} ({lead.get('country', '')})")
            try:
                result = _enrich_one(lead, page, state)
                if result:
                    enriched.append(result)
                    _emit(state, type="agent_status", status="running",
                          message=f"  ✓ {lead['company_name']} | "
                                  f"email: {result.get('email') or '—'} | "
                                  f"contact: {result.get('contact_name') or '—'}")
            except Exception as e:
                _emit(state, type="agent_status", status="running",
                      message=f"  ✗ {lead['company_name']}: {e}")

        context.close()
        browser.close()

    csv_path    = _save_csv(enriched)
    found_email = sum(1 for l in enriched if l.get("email"))

    _emit(state, type="agent_status", status="done",
          message=f"Enrichment complete: {len(enriched)}/{len(to_process)} companies, "
                  f"{found_email} with email. CSV saved.")

    return {
        **state,
        "enriched_leads": enriched,
        "enriched_csv_path": csv_path,
        "current_step": "enrichment_done",
    }



# ── Browser helpers ────────────────────────────────────────────────────────────

def _emit(state: SalesWorkflowState, **kwargs) -> None:
    sse_manager.emit(state.get("thread_id"), {"agent": "browserAgent", **kwargs})


def _make_browser_context(playwright):
    """Launch a stealthy Chromium context (mirrors reference project)."""
    browser = playwright.chromium.launch(
        headless=True,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ],
    )
    context = browser.new_context(
        viewport={"width": 1366, "height": 900},
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        locale="en-US",
    )
    # Hide Playwright fingerprints (from init_script.js in reference project)
    context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        delete window.__playwright;
        delete window.__pw_manual;
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
        Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
    """)
    return browser, context


def _safe_goto(page, url: str, timeout: int = TIMEOUT_MS) -> bool:
    try:
        resp = page.goto(url, timeout=timeout, wait_until="domcontentloaded")
        return resp is not None and resp.status < 400
    except Exception:
        return False


def _page_text(page, max_chars: int = 3000) -> str:
    try:
        return page.inner_text("body")[:max_chars]
    except Exception:
        return ""


# ── Search ─────────────────────────────────────────────────────────────────────

def _duckduckgo_search(page, company: str, country: str) -> tuple[str, list[str]]:
    """Return (search_result_text, [top_result_urls])."""
    query = f'"{company}" {country} contact email'
    url   = f"https://duckduckgo.com/?q={urllib.parse.quote(query)}&ia=web"

    if not _safe_goto(page, url, timeout=20_000):
        return "", []

    try:
        page.wait_for_selector("[data-testid='result']", timeout=SEARCH_WAIT)
    except Exception:
        pass

    text = _page_text(page, 4000)

    urls: list[str] = []
    try:
        for link in page.query_selector_all("a[data-testid='result-title-a']")[:5]:
            href = link.get_attribute("href") or ""
            if href.startswith("http") and "duckduckgo" not in href:
                urls.append(href)
    except Exception:
        pass

    return text, urls


# ── LLM extraction ─────────────────────────────────────────────────────────────

def _parse_json(text: str) -> dict:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        return json.loads(m.group())
    return json.loads(text)


def _llm_extract(company: str, country: str,
                 search_text: str, page_text: str,
                 source_url: str) -> dict:
    prompt = f"""You are a B2B data analyst. Extract contact information for this company from web content.

Company: {company}
Country: {country}

--- SEARCH RESULTS ---
{search_text[:2000]}

--- COMPANY PAGE ---
{page_text[:2000]}

Return ONLY a JSON object:
{{
  "contact_name": "Full name of procurement/import manager or CEO (or null)",
  "email": "Business email address (or null — must not be a personal gmail)",
  "phone": "Phone number with country code (or null)",
  "contact_form_url": "URL of a contact / inquiry form (or null)",
  "company_description": "One sentence describing what the company does",
  "source_url": "Most relevant URL from the content (or empty string)"
}}

Rules:
- Only include information explicitly found in the content above.
- contact_form_url: prefer /contact, /inquiry, /about pages over the homepage."""

    try:
        response = chat(messages=[{"role": "user", "content": prompt}], temperature=0.1)
        return _parse_json(response.content)
    except Exception:
        return {
            "contact_name": None,
            "email": None,
            "phone": None,
            "contact_form_url": source_url or None,
            "company_description": f"Import/export company based in {country}.",
            "source_url": source_url,
        }


# ── Per-lead enrichment ────────────────────────────────────────────────────────

def _enrich_one(lead: RawLead, page) -> Optional[EnrichedLead]:
    company = lead["company_name"]
    country = lead.get("country", "")

    # Step 1 — DuckDuckGo search
    search_text, result_urls = _duckduckgo_search(page, company, country)

    # Step 2 — Visit first reachable result
    page_text  = ""
    source_url = ""
    for url in result_urls[:3]:
        if _safe_goto(page, url):
            page_text  = _page_text(page, 3000)
            source_url = url
            if page_text.strip():
                # Also try the /contact subpage
                try:
                    contact_url = url.rstrip("/") + "/contact"
                    if _safe_goto(page, contact_url, timeout=8_000):
                        extra = _page_text(page, 1500)
                        page_text = page_text + "\n\n[Contact page]\n" + extra
                except Exception:
                    pass
                break

    # Step 3 — LLM extraction
    data = _llm_extract(company, country, search_text, page_text, source_url)

    return EnrichedLead(
        company_name=company,
        contact_name=data.get("contact_name") or "",
        email=data.get("email"),
        phone=data.get("phone"),
        contact_form_url=data.get("contact_form_url") or (source_url or None),
        company_description=data.get("company_description"),
        source_url=data.get("source_url") or source_url or None,
    )


# ── CSV helper ─────────────────────────────────────────────────────────────────

def _save_csv(leads: List[EnrichedLead]) -> str:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = OUTPUT_DIR / f"enriched_leads_{ts}.csv"
    fields   = ["company_name", "contact_name", "email",
                "phone", "contact_form_url", "company_description", "source_url"]
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(leads)
    return str(csv_path)


# ── LangGraph node ─────────────────────────────────────────────────────────────

def enrich_leads(state: SalesWorkflowState) -> SalesWorkflowState:
    """Browser Agent entry point — called by LangGraph."""
    from playwright.sync_api import sync_playwright

    raw_leads: List[RawLead] = state.get("raw_leads") or []
    if not raw_leads:
        _emit(state, type="agent_status", status="error",
              message="No raw leads to enrich.")
        return {**state, "current_step": "error", "error_message": "No raw leads to enrich."}

    to_process = raw_leads[:MAX_LEADS]
    _emit(state, type="agent_status", status="running",
          message=f"Launching browser — enriching {len(to_process)} leads "
                  f"(max {MAX_LEADS} per campaign)...")

    enriched: List[EnrichedLead] = []

    with sync_playwright() as pw:
        browser, context = _make_browser_context(pw)
        page = context.new_page()

        for i, lead in enumerate(to_process, 1):
            _emit(state, type="agent_status", status="running",
                  message=f"({i}/{len(to_process)}) Searching: "
                          f"{lead['company_name']} ({lead.get('country', '')})")
            try:
                result = _enrich_one(lead, page)
                if result:
                    enriched.append(result)
                    email_str   = result.get("email") or "—"
                    contact_str = result.get("contact_name") or "—"
                    _emit(state, type="agent_status", status="running",
                          message=f"  ✓ {lead['company_name']} | "
                                  f"email: {email_str} | contact: {contact_str}")
            except Exception as e:
                _emit(state, type="agent_status", status="running",
                      message=f"  ✗ {lead['company_name']}: {e}")

        context.close()
        browser.close()

    csv_path    = _save_csv(enriched)
    found_email = sum(1 for l in enriched if l.get("email"))

    _emit(state, type="agent_status", status="done",
          message=f"Enrichment complete: {len(enriched)}/{len(to_process)} companies, "
                  f"{found_email} with email. CSV saved.")

    return {
        **state,
        "enriched_leads": enriched,
        "enriched_csv_path": csv_path,
        "current_step": "enrichment_done",
    }
