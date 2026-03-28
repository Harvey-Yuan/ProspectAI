"""
CRM Agent - Outreach Execution
================================
For each approved enriched lead:
  1. Compose a personalised email using GPT-4o.
  2. Select the best delivery channel (email > contact form > phone).
  3. Deliver and log the result.

Dependencies (to be installed):
    langchain-openai, resend (or sendgrid), playwright
"""

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import List

import sse_manager
from state import SalesWorkflowState, EnrichedLead, ActivityEntry, CompanyProfile

OUTPUT_DIR = Path(__file__).parent.parent / "output"


def _emit(state: SalesWorkflowState, **kwargs) -> None:
    sse_manager.emit(state.get("thread_id"), {"agent": "crmAgent", **kwargs})


def _compose_email(lead: EnrichedLead, profile: CompanyProfile) -> str:
    """
    TODO: call GPT-4o to write a personalised outreach email.

    Context for the prompt:
      - Sender: profile["ai_persona_name"] at profile["company_name"]
      - Value prop: profile["description"]
      - Recipient: lead["contact_name"] at lead["company_name"]
      - Personalisation hook: lead["company_description"]
    """
    raise NotImplementedError("Email composition via GPT-4o not yet implemented")


def _send_email(to: str, subject: str, body: str, sender: str) -> bool:
    """TODO: send via Resend or SendGrid API. Returns True on success."""
    raise NotImplementedError("Email delivery not yet implemented")


def _submit_contact_form(url: str, lead: EnrichedLead, body: str) -> bool:
    """TODO: use Playwright to fill and submit the contact form at `url`."""
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
    profile: CompanyProfile = state.get("company_profile") or {}

    if not leads:
        _emit(state, type="agent_status", status="running",
              message="No approved contacts to reach out to "
                      "(Browser Agent not yet implemented — skipping sends).")
        return {**state, "activity_log": [], "current_step": "outreach_done"}

    _emit(state, type="agent_status", status="running",
          message=f"Composing personalised emails for {len(leads)} contacts...")

    log: List[ActivityEntry] = []
    for i, lead in enumerate(leads, 1):
        now = datetime.now(timezone.utc).isoformat()
        channel, status, preview = "unknown", "pending", ""

        _emit(state, type="agent_status", status="running",
              message=f"({i}/{len(leads)}) Processing: {lead.get('company_name', '')}")

        try:
            body = _compose_email(lead, profile)
            preview = body[:200]
            if lead.get("email"):
                channel = "email"
                ok = _send_email(
                    lead["email"],
                    f"Partnership opportunity — {profile.get('company_name', '')}",
                    body,
                    profile.get("sender_email", ""),
                )
                status = "sent" if ok else "failed"
            elif lead.get("contact_form_url"):
                channel = "form"
                ok = _submit_contact_form(lead["contact_form_url"], lead, body)
                status = "sent" if ok else "failed"
        except NotImplementedError:
            status = "pending"
        except Exception as e:
            _emit(state, type="agent_status", status="running",
                  message=f"Warning: outreach failed for {lead.get('company_name', '')}: {e}")

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
          message=f"Outreach complete: {sent}/{len(log)} sent "
                  f"(email delivery not yet implemented).")

    _save_activity_log(log)
    return {**state, "activity_log": log, "current_step": "outreach_done"}
