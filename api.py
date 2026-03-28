"""
FastAPI Backend - AI Sales Agent
==================================
Endpoints:
  POST /api/campaign/start          -- Start a new campaign, returns thread_id
  GET  /api/campaign/{id}/stream    -- SSE stream of all agent events
  POST /api/campaign/{id}/approve   -- Submit human approval and resume graph

  GET  /auth/google                 -- Redirect to Google OAuth consent
  GET  /auth/callback               -- Handle OAuth callback
  GET  /auth/me                     -- Current user info
  POST /auth/logout                 -- Clear session
"""

import asyncio
import json
import os
import queue as _queue
import threading
import traceback
import uuid
from typing import List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request

load_dotenv()

import auth
import sse_manager
from graph import graph
from state import SalesWorkflowState, CompanyProfile

app = FastAPI(title="AI Sales Agent API")

# Session middleware must be added before CORS and routes
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SESSION_SECRET", "change-me-in-production"),
    session_cookie="ai_sales_session",
    max_age=86400,   # 24 hours
    https_only=False,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount Google OAuth routes
app.include_router(auth.router)


# ── Request / Response models ────────────────────────────────────────────────

class CompanyProfileRequest(BaseModel):
    company_name: str
    products: str
    target_segment: str
    description: str
    ai_persona_name: str
    sender_email: str


class ApprovalRequest(BaseModel):
    approved: bool
    edited_leads: Optional[List[dict]] = None


# ── Background graph runner ──────────────────────────────────────────────────

def _run_graph(thread_id: str, profile: CompanyProfileRequest,
               gmail_token: Optional[dict]) -> None:
    """Runs the full LangGraph workflow in a background thread."""
    config = {"configurable": {"thread_id": thread_id}}

    initial_state: SalesWorkflowState = {
        "thread_id": thread_id,
        "gmail_token": gmail_token,
        "company_profile": CompanyProfile(
            company_name=profile.company_name,
            products=profile.products,
            target_segment=profile.target_segment,
            description=profile.description,
            ai_persona_name=profile.ai_persona_name,
            sender_email=profile.sender_email,
        ),
        "search_params": None,
        "raw_leads": None,
        "leads_csv_path": None,
        "enriched_leads": None,
        "enriched_csv_path": None,
        "human_approved": False,
        "approved_leads": None,
        "activity_log": None,
        "current_step": "init",
        "error_message": None,
        "messages": [],
    }

    try:
        # Phase 1: run until interrupt_before human_review
        for _ in graph.stream(initial_state, config):
            pass

        snapshot = graph.get_state(config)
        interrupted = bool(snapshot.next)

        if not interrupted:
            sse_manager.emit(thread_id, {
                "type": "workflow_done",
                "agent": "masterAgent",
                "message": "Workflow completed.",
            })
            return

        # Pause: ask user to review enriched contacts
        enriched = snapshot.values.get("enriched_leads") or []
        sse_manager.emit(thread_id, {
            "type": "human_review_needed",
            "agent": "masterAgent",
            "message": f"Paused — awaiting human review of {len(enriched)} enriched contacts.",
            "enriched_leads": enriched,
        })

        # Block until approved (up to 10 minutes)
        approval = sse_manager.wait_for_approval(thread_id, timeout=600)

        if not approval or not approval.get("approved"):
            sse_manager.emit(thread_id, {
                "type": "error",
                "agent": "masterAgent",
                "message": "Campaign cancelled by user.",
            })
            return

        approved_leads = approval.get("edited_leads") or enriched
        graph.update_state(config, {
            "human_approved": True,
            "approved_leads": approved_leads,
        })

        sse_manager.emit(thread_id, {
            "type": "agent_status",
            "agent": "masterAgent",
            "status": "running",
            "message": f"Review approved ({len(approved_leads)} contacts). Resuming workflow...",
        })

        # Phase 2: CRM agent to completion
        for _ in graph.stream(None, config):
            pass

        sse_manager.emit(thread_id, {
            "type": "workflow_done",
            "agent": "masterAgent",
            "message": "Campaign finished successfully!",
        })

    except Exception:
        traceback.print_exc()
        sse_manager.emit(thread_id, {
            "type": "error",
            "agent": "masterAgent",
            "message": "An unexpected error occurred. Check server logs.",
        })
    finally:
        sse_manager.close(thread_id)


# ── API routes ───────────────────────────────────────────────────────────────

@app.post("/api/campaign/start")
async def start_campaign(profile: CompanyProfileRequest, request: Request):
    thread_id   = str(uuid.uuid4())
    gmail_token = request.session.get("gmail_token")   # None if not logged in
    sse_manager.setup(thread_id)
    threading.Thread(
        target=_run_graph,
        args=(thread_id, profile, gmail_token),
        daemon=True,
    ).start()
    return {"thread_id": thread_id}


@app.get("/api/campaign/{thread_id}/stream")
async def stream_campaign(thread_id: str):
    q = sse_manager.get_sse_queue(thread_id)
    if q is None:
        raise HTTPException(status_code=404, detail="Campaign not found")

    async def generator():
        loop = asyncio.get_running_loop()
        while True:
            try:
                event = await loop.run_in_executor(None, q.get, True, 1.0)
                if event is None:
                    yield f"data: {json.dumps({'type': 'done'})}\n\n"
                    return
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            except _queue.Empty:
                yield ": heartbeat\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
                return

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/campaign/{thread_id}/approve")
async def approve_campaign(thread_id: str, body: ApprovalRequest):
    if sse_manager.get_sse_queue(thread_id) is None:
        raise HTTPException(status_code=404, detail="Campaign not found or already completed")
    sse_manager.send_approval(thread_id, body.model_dump())
    return {"ok": True}


@app.post("/api/test-email")
async def test_email(request: Request):
    """Send a test email to the currently logged-in Gmail account."""
    gmail_token = request.session.get("gmail_token")
    user        = request.session.get("user")
    if not gmail_token or not user:
        raise HTTPException(status_code=401, detail="Not authenticated with Gmail")

    to_email  = user.get("email", "")
    user_name = user.get("name", "there")
    if not to_email:
        raise HTTPException(status_code=400, detail="No email address in session")

    ok = auth.send_gmail(
        gmail_token,
        to=to_email,
        subject="✅ AI Sales Agent — Gmail connection test",
        body=(
            f"Hi {user_name},\n\n"
            "Your Gmail account is successfully connected to AI Sales Agent! 🎉\n\n"
            "You can now launch campaigns and send personalised outreach emails "
            "directly from your inbox.\n\n"
            "— AI Sales Agent"
        ),
    )
    if not ok:
        raise HTTPException(status_code=500, detail="Gmail API returned an error")
    return {"ok": True, "sent_to": to_email}


# Static frontend — must be mounted LAST
app.mount("/", StaticFiles(directory="frontend", html=True), name="static")
