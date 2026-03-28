# Product Requirements Document — AI Sales Outreach Multi-Agent System (MVP)

**Version:** 0.1  
**Date:** 2026-03-28  
**Status:** Draft

---

## 1. Overview

### 1.1 Problem Statement

Sales teams spend significant time manually researching prospective customers and crafting individual outreach emails. This process is slow, inconsistent, and difficult to scale.

### 1.2 Product Vision

Build a multi-agent AI system that automatically discovers potential customers from trade/customs data, enriches their contact information via web research, and sends personalized outreach emails — all with minimal human intervention.

---

## 2. Users & Use Cases

**Primary User:** B2B sales representative or founder of an export/import company.

**Core Use Case:**
> A user configures their company profile, uploads trade data, and the system automatically identifies prospects, finds their contact details, and sends tailored outreach — returning a full activity log for review.

---

## 3. System Architecture — Multi-Agent Design

The system is composed of one **Master Agent** orchestrating three **Sub-Agents**.

```
User Input
    │
    ▼
┌─────────────────────────────┐
│   Master Agent (AI Sales)   │  ◄── Company Profile (.md / form)
└────────────┬────────────────┘
             │ orchestrates
    ┌────────┼─────────┐
    ▼        ▼         ▼
[Data    [Browser  [CRM
 Agent]   Agent]    Agent]
    │        │         │
    └────────┴─────────┘
             │
          Output: Activity Log
```

---

## 4. Agent Specifications

### 4.1 Master Agent — "AI Sales"

**Role:** Central orchestrator. Holds company context, delegates tasks to sub-agents, and manages overall workflow state.

**Inputs:**
- Company profile (via onboarding form or `.md` file):
  - Company name
  - Products / services offered
  - Target customer segment
  - Company description / value proposition
  - AI Sales persona name
  - Sender email address

**Responsibilities:**
- Parse and store company profile
- Trigger Data Agent to retrieve trade leads
- Pass leads + instructions to Browser Agent
- Review enriched CSV (Human-in-the-Loop checkpoint)
- Trigger CRM Agent for outreach
- Collect and surface final activity log

**Output:** Workflow state; final activity log

---

### 4.2 Data Agent — Lead Source

**Role:** Retrieves raw prospect records from a trade/customs data source.

**Inputs:**
- Search parameters from Master Agent (industry, country, product HS code, etc.)

**Process:**
1. Query customs / trade database (e.g., ImportYeti, Panjiva API, or uploaded CSV)
2. Parse and normalize records
3. Deduplicate against previously processed leads

**Output:** Structured list of company names + country of origin (seed data for Browser Agent)

---

### 4.3 Browser Agent — Contact Enrichment

**Role:** Uses web browsing + LLM reasoning to find detailed contact information for each prospect company.

**Inputs:**
- Company name + country (from Data Agent)
- Search strategy instructions from Master Agent

**Process:**

**Step A — Direct Search (Required):**
1. Search `[company name] + contact / email / about`
2. Visit company website, LinkedIn, and business directories
3. Extract:
   - `company_name`
   - `contact_person_name`
   - `email`
   - `phone`
   - `contact_form_url`
   - `company_description` (used for personalization)

**Step B — Heuristic Discovery (Optional / v1.1):**
- Identify similar companies based on industry/product overlap
- Repeat Step A for discovered companies

**Output:**  
Enriched CSV file:

| Field | Description |
|---|---|
| `company_name` | Full legal name |
| `contact_name` | Decision-maker name (e.g., CEO, Purchasing Manager) |
| `email` | Primary business email |
| `phone` | Phone number (optional) |
| `contact_form_url` | Web form URL if no email found |
| `company_description` | Short summary for email personalization |
| `source_url` | Where the info was found |

**Human-in-the-Loop Checkpoint:**  
Before CRM Agent runs, the user reviews and approves the enriched CSV in the UI.

---

### 4.4 CRM Agent — Outreach Execution

**Role:** Composes personalized outreach messages and delivers them via the best available channel.

**Inputs:**
- Approved enriched CSV
- Company profile from Master Agent

**Process:**

For each lead:

1. **Compose personalized email** using:
   - `contact_name` (salutation)
   - `company_description` (relevance hook)
   - Sender's company value proposition

2. **Select delivery channel:**

   | Condition | Action |
   |---|---|
   | `email` is present | Send email via sender's SMTP / email API |
   | `email` missing, `contact_form_url` present | Fill and submit web contact form |
   | `phone` present *(v1.1 optional)* | Initiate AI phone call |

3. Log result per lead (sent / failed / pending)

**Output:** Activity log CSV / dashboard entry:

| Field |
|---|
| `company_name` |
| `contact_name` |
| `channel_used` (email / form / phone) |
| `status` (sent / failed) |
| `timestamp` |
| `email_preview` |

---

## 5. UI Requirements (MVP)

### 5.1 Onboarding Screen
- Form: company name, products, target customers, description, AI persona name, sender email
- Upload option: `.md` company profile file

### 5.2 Dashboard / Run Screen
- "Start New Campaign" button
- Real-time status panel showing active agent and current step:
  - `Data Agent: fetching leads…`
  - `Browser Agent: enriching 12/20 companies…`
  - `CRM Agent: sending emails…`

### 5.3 Human-in-the-Loop Review Screen
- Spreadsheet-style view of enriched CSV before sending
- User can edit, delete, or approve individual rows
- "Approve & Send" confirmation button

### 5.4 Activity Log Screen
- Table of all outreach attempts
- Columns: company, contact, channel, status, timestamp, email preview (expandable)
- Basic stats: total sent, success rate

---

## 6. Technical Stack (Suggested)

| Component | Choice |
|---|---|
| Agent framework | LangGraph |
| LLM | GPT-4o (orchestration + writing) |
| Browser automation | Playwright + Browser-use |
| Email delivery | SendGrid / Resend API |
| Form filling | Playwright |
| Data storage | SQLite (MVP) |
| Frontend | Next.js + Tailwind CSS |
| Backend API | FastAPI (Python) |

---

## 7. Out of Scope for MVP

- AI phone calling (marked as v1.1)
- Heuristic company discovery (marked as v1.1)
- Multi-user / team accounts
- CRM integrations (Salesforce, HubSpot)
- A/B testing email variants
- Automated follow-up sequences

---

## 8. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Browser agent fails to find email | Fall back to contact form URL; flag in UI |
| Email marked as spam | Use reputable ESP; personalize subject line; rate-limit sends |
| Trade data quality is low | Allow manual CSV upload as fallback input |
| Web scraping blocked | Rotate user-agents; add retry logic; respect robots.txt |

---

## 9. MVP Milestone Plan

| Milestone | Deliverable | Timeline |
|---|---|---|
| M1 | Master Agent + Data Agent (static CSV input) | Week 1–2 |
| M2 | Browser Agent — contact enrichment for 20 leads | Week 3–4 |
| M3 | CRM Agent — email send + form fill | Week 5–6 |
| M4 | UI (onboarding + review + log) | Week 7–8 |
| M5 | End-to-end integration test + bug fixes | Week 9 |
| **MVP Launch** | **Internal beta with real campaign** | **Week 10** |
