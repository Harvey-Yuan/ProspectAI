"""
CRM Agent - Outreach Execution
================================
For each approved enriched lead:
  1. Compose a personalised email using GPT-4o.
  2. Select the best delivery channel (Gmail API > contact form > phone).
  3. Deliver and log the result.

Gmail sending uses the OAuth token stored in state["gmail_token"].
Contact form submission uses Playwright (not yet implemented).
"""

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import sse_manager
from llm_client import chat
from state import SalesWorkflowState, EnrichedLead, ActivityEntry, CompanyProfile

OUTPUT_DIR = Path(__file__).parent.parent / "output"


def _emit(state: SalesWorkflowState, **kwargs) -> None:
    sse_manager.emit(state.get("thread_id"), {"agent": "crmAgent", **kwargs})


def _compose_email(lead: EnrichedLead, profile: CompanyProfile) -> str:
    """Use LLM to write a personalised outreach email for the given lead."""
    company_context = lead.get("company_description") or f"a company in {lead.get('company_name', 'your industry')}"
    contact_name = lead.get("contact_name") or "the Procurement Manager"

    prompt = f"""You are {profile['ai_persona_name']}, a sales representative at {profile['company_name']}.

Write a short, personalised B2B cold outreach email to {contact_name} at {lead.get('company_name', '')}.

About your company:
- Company: {profile['company_name']}
- Products/services: {profile['products']}
- Value proposition: {profile['description']}

About the recipient's company:
{company_context}

Requirements:
- Professional but warm tone, not generic or spammy
- 3 short paragraphs: hook → value prop → CTA
- Reference something specific about their company in the opening line
- Clear call-to-action: suggest a brief 15-min call or a reply with questions
- Sign off as {profile['ai_persona_name']} at {profile['company_name']}
- Plain text only — no markdown, no bullet points, no subject line
- Write the email body ONLY, starting directly with the greeting (e.g. "Hi {contact_name},")"""

    response = chat(messages=[{"role": "user", "content": prompt}], temperature=0.7)
    return response.content.strip()


def _send_via_gmail(gmail_token: dict, to: str, subject: str, body: str) -> bool:
    """Send email using the user's Gmail OAuth token via the Gmail REST API."""
    from auth import send_gmail
    return send_gmail(gmail_token, to, subject, body)


def _submit_contact_form(url: str, lead: EnrichedLead, body: str) -> bool:
    """TODO: use Playwright to fill and submit the contact form at url."""
    raise NotImplementedError("Contact form submission not yet implemented")


def _save_activity_log(log: List[ActivityEntry]) -> str:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = OUTPUT_DIR / f"activity_log_{ts}.csv"
    fieldnames = ["company_name", "contact_name", "channel_used",
                  "status", "timestamp", "email_preview"]
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(log)
    return str(csv_path)


def send_outreach(state: SalesWorkflowState) -> SalesWorkflowState:
    """LangGraph node - CRM Agent entry point."""
    leads: List[EnrichedLead] = state.get("approved_leads") or []
    profile: CompanyProfile   = state.get("company_profile") or {}
    gmail_token: Optional[dict] = state.get("gmail_token")

    if not leads:
        _emit(state, type="agent_status", status="running",
              message="No approved contacts to reach out to "
                      "(Browser Agent not yet implemented — skipping sends).")
        return {**state, "activity_log": [], "current_step": "outreach_done"}

    # Inform the user about the sending channel
    if gmail_token:
        _emit(state, type="agent_status", status="running",
              message=f"Gmail connected — composing and sending emails for {len(leads)} contacts...")
    else:
        _emit(state, type="agent_status", status="running",
              message=f"No Gmail token — will mark emails as pending. "
                      f"Sign in with Google to enable real sending.")

    log: List[ActivityEntry] = []
    for i, lead in enumerate(leads, 1):
        now     = datetime.now(timezone.utc).isoformat()
        channel = "unknown"
        status  = "pending"
        preview = ""

        _emit(state, type="agent_status", status="running",
              message=f"({i}/{len(leads)}) Processing: {lead.get('company_name', '')}")

        try:
            body    = _compose_email(lead, profile)
            preview = body[:200]

            if lead.get("email"):
                channel = "email"
                if gmail_token:
                    ok = _send_via_gmail(
                        gmail_token,
                        to=lead["email"],
                        subject=f"Partnership opportunity — {profile.get('company_name', '')}",
                        body=body,
                    )
                    status = "sent" if ok else "failed"
                    if ok:
                        _emit(state, type="agent_status", status="running",
                              message=f"  ✓ Email sent to {lead['email']}")
                else:
                    status = "pending"
                    _emit(state, type="agent_status", status="running",
                          message=f"  ⚠ Skipped (no Gmail token): {lead['email']}")

            elif lead.get("contact_form_url"):
                channel = "form"
                ok = _submit_contact_form(lead["contact_form_url"], lead, body)
                status = "sent" if ok else "failed"

        except NotImplementedError:
            status = "pending"
        except Exception as e:
            _emit(state, type="agent_status", status="running",
                  message=f"  ✗ Error for {lead.get('company_name', '')}: {e}")

        log.append(ActivityEntry(
            company_name=lead.get("company_name", ""),
            contact_name=lead.get("contact_name", ""),
            channel_used=channel,
            status=status,
            timestamp=now,
            email_preview=preview,
        ))

    sent = sum(1 for e in log if e["status"] == "sent")
    _emit(state, type="agent_status", status="done",
          message=f"Outreach complete: {sent}/{len(log)} sent successfully.")

    _save_activity_log(log)
    return {**state, "activity_log": log, "current_step": "outreach_done"}
