"""
FastAPI Backend - AI Sales Agent
==================================
Endpoints:
  POST /api/campaign/start          -- Start a new campaign, returns thread_id
  GET  /api/campaign/{id}/stream    -- SSE stream of all agent events
  POST /api/campaign/{id}/approve   -- Submit human approval and resume graph
"""

import asyncio
import json
import queue as _queue
import threading
import traceback
import uuid
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import sse_manager
from graph import graph
from state import SalesWorkflowState, CompanyProfile

app = FastAPI(title="AI Sales Agent API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


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

def _run_graph(thread_id: str, profile: CompanyProfileRequest) -> None:
    """Runs the full LangGraph workflow in a background thread."""
    config = {"configurable": {"thread_id": thread_id}}

    initial_state: SalesWorkflowState = {
        "thread_id": thread_id,
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
            # Workflow ended before reaching human_review (likely an error)
            sse_manager.emit(thread_id, {
                "type": "workflow_done",
                "agent": "masterAgent",
                "message": "Workflow completed.",
            })
            return

        # Notify the frontend that human review is needed
        enriched = snapshot.values.get("enriched_leads") or []
        sse_manager.emit(thread_id, {
            "type": "human_review_needed",
            "agent": "masterAgent",
            "message": f"Paused — awaiting human review of {len(enriched)} enriched contacts.",
            "enriched_leads": enriched,
        })

        # Block this thread until the user approves (up to 10 minutes)
        approval = sse_manager.wait_for_approval(thread_id, timeout=600)

        if not approval or not approval.get("approved"):
            sse_manager.emit(thread_id, {
                "type": "error",
                "agent": "masterAgent",
                "message": "Campaign cancelled by user.",
            })
            return

        # Resume the graph with the approved leads
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

        # Phase 2: run CRM agent to completion
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
async def start_campaign(profile: CompanyProfileRequest):
    thread_id = str(uuid.uuid4())
    sse_manager.setup(thread_id)
    threading.Thread(target=_run_graph, args=(thread_id, profile), daemon=True).start()
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
                # Block at most 1 second so the loop stays responsive
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


# Static frontend — must be mounted LAST to avoid shadowing API routes
app.mount("/", StaticFiles(directory="frontend", html=True), name="static")
