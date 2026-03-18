"""
Daemon Watcher — Relay Server
==============================
Heartbeat broker for cross-network node sync.

Each node POSTs its heartbeat here and GETs all peer statuses.
Authentication uses the Telegram bot_token the customer already has —
no new credentials required.

Namespacing: sha256(bot_token + chat_id)[:16]
  → Different bot/chat installations never see each other's nodes.
  → Raw tokens are never stored or logged.

Run locally:
  python3 relay_server.py
  python3 relay_server.py --host 0.0.0.0 --port 8080

Deploy to Render / Railway / Fly.io:
  Build context: project root
  Start command: python3 relay_server.py --host 0.0.0.0 --port $PORT
  (or use: uvicorn relay_server:app --host 0.0.0.0 --port $PORT)

Environment variables (optional):
  NODE_TTL_SECONDS  — how long a node stays alive without a heartbeat (default: 90)
  MAX_NODES_PER_NS  — max nodes per namespace to prevent abuse (default: 50)
  PORT              — port to listen on when run directly (default: 8000)
"""

import argparse
import hashlib
import os
import threading
import time
from typing import Dict, Any, Optional

from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

NODE_TTL  = int(os.getenv("NODE_TTL_SECONDS", "90"))   # 6× default 15s heartbeat interval
MAX_NODES = int(os.getenv("MAX_NODES_PER_NS",  "50"))

# ---------------------------------------------------------------------------
# In-memory store  { namespace: { machine_id: { ...payload, _expires: float } } }
# ---------------------------------------------------------------------------

_store: Dict[str, Dict[str, Any]] = {}
_lock  = threading.Lock()


def _ns(bot_token: str, chat_id: str) -> str:
    """Opaque namespace key — raw token is never stored."""
    return hashlib.sha256(f"{bot_token}:{chat_id}".encode()).hexdigest()[:16]


def _evict() -> None:
    """Remove expired entries. Called on every write to keep memory bounded."""
    now = time.time()
    with _lock:
        for ns in list(_store):
            _store[ns] = {
                mid: node
                for mid, node in _store[ns].items()
                if node.get("_expires", 0) > now
            }
            if not _store[ns]:
                del _store[ns]


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

app = FastAPI(title="Daemon Watcher Relay", docs_url=None, redoc_url=None)


class HeartbeatPayload(BaseModel):
    chat_id:     str
    machine_id:  str
    custom_name: Optional[str] = None
    hostname:    Optional[str] = None
    platform:    Optional[str] = None
    is_running:  bool  = True
    last_seen:   float


@app.post("/heartbeat", status_code=200)
def post_heartbeat(
    payload:       HeartbeatPayload,
    x_bot_token:   str = Header(..., alias="X-Bot-Token"),
):
    """Node publishes its current status."""
    _evict()
    ns = _ns(x_bot_token, payload.chat_id)

    with _lock:
        bucket = _store.setdefault(ns, {})
        if payload.machine_id not in bucket and len(bucket) >= MAX_NODES:
            raise HTTPException(status_code=429, detail="namespace node limit reached")
        bucket[payload.machine_id] = {
            "machine_id":  payload.machine_id,
            "custom_name": payload.custom_name,
            "hostname":    payload.hostname,
            "platform":    payload.platform,
            "is_running":  payload.is_running,
            "last_seen":   payload.last_seen,
            "_expires":    time.time() + NODE_TTL,
        }

    return {"ok": True}


@app.get("/nodes")
def get_nodes(
    chat_id:     str = Query(...),
    x_bot_token: str = Header(..., alias="X-Bot-Token"),
):
    """Node fetches all peer statuses for this bot+chat namespace."""
    _evict()
    ns  = _ns(x_bot_token, chat_id)
    now = time.time()

    with _lock:
        raw = dict(_store.get(ns, {}))

    nodes = {
        mid: {k: v for k, v in node.items() if not k.startswith("_")}
        for mid, node in raw.items()
        if node.get("_expires", 0) > now
    }
    return {"nodes": nodes}


@app.get("/health")
def health():
    """Liveness probe."""
    with _lock:
        ns_count   = len(_store)
        node_count = sum(len(v) for v in _store.values())
    return {"ok": True, "namespaces": ns_count, "nodes": node_count}


# ---------------------------------------------------------------------------
# Entry point — same pattern as the daemon
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    parser = argparse.ArgumentParser(description="Daemon Watcher Relay Server")
    parser.add_argument("--host", default="0.0.0.0",                          help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", 8000)), help="Bind port (default: 8000)")
    args = parser.parse_args()

    print(f"[Relay] Daemon Watcher Relay Server starting on {args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port)
