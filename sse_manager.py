"""
Thread-safe SSE event bus and human-approval gate.

The background graph thread emits events via emit().
The async FastAPI SSE generator reads from the queue via get_sse_queue().
The approval gate uses a separate queue: the graph thread blocks on
wait_for_approval(), and the API endpoint unblocks it via send_approval().
"""

import queue
import threading
from typing import Any, Dict, Optional

_sse: Dict[str, queue.Queue] = {}
_approval: Dict[str, queue.Queue] = {}
_lock = threading.Lock()


def setup(thread_id: str) -> None:
    """Create SSE and approval queues for a new campaign thread."""
    with _lock:
        _sse[thread_id] = queue.Queue()
        _approval[thread_id] = queue.Queue()


def emit(thread_id: Optional[str], event: Dict[str, Any]) -> None:
    """Push an SSE event onto the queue for the given campaign."""
    if not thread_id:
        return
    with _lock:
        q = _sse.get(thread_id)
    if q:
        q.put(event)


def get_sse_queue(thread_id: str) -> Optional[queue.Queue]:
    """Return the SSE queue for the FastAPI generator to read from."""
    with _lock:
        return _sse.get(thread_id)


def wait_for_approval(thread_id: str, timeout: float = 600.0) -> Optional[Dict]:
    """Block the calling thread until the user approves or the timeout expires."""
    with _lock:
        q = _approval.get(thread_id)
    if not q:
        return None
    try:
        return q.get(timeout=timeout)
    except queue.Empty:
        return None


def send_approval(thread_id: str, data: Dict[str, Any]) -> None:
    """Unblock wait_for_approval by pushing the approval payload."""
    with _lock:
        q = _approval.get(thread_id)
    if q:
        q.put(data)


def close(thread_id: str) -> None:
    """Send the sentinel None to stop the SSE generator, then clean up."""
    with _lock:
        sse_q = _sse.pop(thread_id, None)
        _approval.pop(thread_id, None)
    if sse_q:
        sse_q.put(None)  # None signals the generator to close the stream
