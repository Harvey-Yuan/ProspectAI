# AI Sales Outreach Multi-Agent System

Automatically find prospects from trade data, enrich their contact info, and send personalized outreach emails.

## How it works

1. **Data Agent** — pulls leads from customs/trade data
2. **Browser Agent** — searches the web to find company email, contact name, and form URL
3. **CRM Agent** — writes and sends a personalized email (or fills a contact form)

A **Master Agent** orchestrates all three.

## Stack

- LangGraph / CrewAI · GPT-4o · Playwright · FastAPI · Next.js

## Getting Started

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies and create .venv
uv sync

# Install Playwright browser
uv run playwright install chromium

# Run
uv run python main.py
```

## Docs

- [`prd.md`](./prd.md) — full product requirements
