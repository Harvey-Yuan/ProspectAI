"""
CRM Agent — Outreach Execution
================================
For each approved enriched lead:
  1. Compose a personalised email using GPT-4o.
  2. Select the best delivery channel (email > contact form > phone).
  3. Deliver and log the result.

Dependencies (to be installed):
    langchain, langchain-openai, resend (or sendgrid), playwright
"""

import csv
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from state import SalesWorkflowState, EnrichedLead, ActivityEntry, CompanyProfile

OUTPUT_DIR = Path(__file__).parent.parent / "output"


def _compose_email(
    lead: EnrichedLead,
    profile: CompanyProfile,
) -> str:
    """
    TODO: call GPT-4o to write a personalised outreach email.

    Prompt context:
      - Sender: profile["ai_persona_name"] at profile["company_name"]
      - Value prop: profile["description"]
      - Recipient: lead["contact_name"] at lead["company_name"]
      - Hook: lead["company_description"]
    """
    raise NotImplementedError("Email composition via GPT-4o not yet implemented")


def _send_email(to_address: str, subject: str, body: str, sender_email: str) -> bool:
    """
    TODO: send via Resend or SendGrid API.
    Returns True on success.
    """
    raise NotImplementedError("Email delivery not yet implemented")


def _submit_contact_form(url: str, lead: EnrichedLead, body: str) -> bool:
    """
    TODO: use Playwright to fill and submit the contact form at `url`.
    Returns True on success.
    """
    raise NotImplementedError("Contact form submission not yet implemented")


def _save_activity_log(log: List[ActivityEntry]) -> str:
    """Persist activity log to CSV and return path."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = OUTPUT_DIR / f"activity_log_{timestamp}.csv"

    fieldnames = ["company_name", "contact_name", "channel_used", "status", "timestamp", "email_preview"]
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(log)

    return str(csv_path)


def send_outreach(state: SalesWorkflowState) -> SalesWorkflowState:
    """
    LangGraph node — CRM Agent entry point.
    Iterates over approved leads, composes messages, and delivers them.
    """
    leads: List[EnrichedLead] = state.get("approved_leads") or []
    profile: CompanyProfile = state.get("company_profile") or {}

    if not leads:
        return {
            **state,
            "current_step": "error",
            "error_message": "No approved leads to contact.",
        }

    print(f"[CRMAgent] Starting outreach for {len(leads)} leads...")

    log: List[ActivityEntry] = []

    for lead in leads:
        now = datetime.now(timezone.utc).isoformat()
        channel = "unknown"
        status = "failed"
        email_preview = ""

        try:
            body = _compose_email(lead, profile)
            email_preview = body[:200]

            if lead.get("email"):
                channel = "email"
                success = _send_email(
                    to_address=lead["email"],
                    subject=f"Partnership opportunity — {profile.get('company_name', '')}",
                    body=body,
                    sender_email=profile.get("sender_email", ""),
                )
                status = "sent" if success else "failed"

            elif lead.get("contact_form_url"):
                channel = "form"
                success = _submit_contact_form(lead["contact_form_url"], lead, body)
                status = "sent" if success else "failed"

            else:
                status = "pending"
                channel = "none"

        except NotImplementedError:
            status = "pending"
        except Exception as e:
            print(f"[CRMAgent] Error contacting {lead['company_name']}: {e}")

        log.append(
            ActivityEntry(
                company_name=lead.get("company_name", ""),
                contact_name=lead.get("contact_name", ""),
                channel_used=channel,
                status=status,
                timestamp=now,
                email_preview=email_preview,
            )
        )

    csv_path = _save_activity_log(log)
    print(f"[CRMAgent] Activity log saved → {csv_path}")

    return {
        **state,
        "activity_log": log,
        "current_step": "outreach_done",
    }
