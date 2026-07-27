"""
main.py — FastAPI application entrypoint.

Exposes:
  - GET  /api/state                snapshot of current kernel state
  - POST /api/control/{action}      play/pause/step/reset/speed
  - POST /api/scheduler/algorithm   change scheduling algorithm
  - POST /api/memory/policy         change page replacement policy
  - POST /api/process/spawn         spawn a new process
  - POST /api/process/{pid}/kill    kill a process
  - POST /api/interrupt/{irq}       inject an interrupt
  - POST /api/memory/pressure       trigger memory pressure
  - POST /api/workload              generate a batch of random workload
  - POST /api/chat                  ask the AI assistant a question
  - WS   /ws                        real-time state stream

Run with: uvicorn backend.main:app --reload --port 8000
"""

from __future__ import annotations
import asyncio
import json
from contextlib import asynccontextmanager

import os
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .kernel.kernel import Kernel

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")

kernel = Kernel()
_connections: set[WebSocket] = set()
_sim_task: asyncio.Task | None = None
_running = True
_speed = 1.0
_step_once = False


async def _simulation_loop():
    global _step_once
    while True:
        await asyncio.sleep(max(0.05, 0.5 / _speed))
        if _running or _step_once:
            snapshot = kernel.tick()
            _step_once = False
            dead = set()
            for ws in _connections:
                try:
                    await ws.send_text(json.dumps(snapshot))
                except Exception:
                    dead.add(ws)
            _connections.difference_update(dead)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _sim_task
    _sim_task = asyncio.create_task(_simulation_loop())
    yield
    if _sim_task:
        _sim_task.cancel()


app = FastAPI(title="AI-Aware Microkernel OS Simulator", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)


# ---------------------------------------------------------------- models
class SpawnRequest(BaseModel):
    name: str = "user_task"
    priority: int = 5
    burst_time: int = 6
    memory_required: int = 4
    io_bound: bool = False


class AlgorithmRequest(BaseModel):
    algorithm: str


class PolicyRequest(BaseModel):
    policy: str


class ChatRequest(BaseModel):
    question: str


class SpeedRequest(BaseModel):
    speed: float


# ---------------------------------------------------------------- REST
@app.get("/api/state")
def get_state():
    return kernel.snapshot()


@app.post("/api/control/{action}")
def control(action: str):
    global _running, _step_once
    if action == "play":
        _running = True
    elif action == "pause":
        _running = False
    elif action == "step":
        _running = False
        _step_once = True
    elif action == "reset":
        global kernel
        kernel = Kernel()
        _running = True
    else:
        return {"error": f"unknown action {action}"}
    return {"status": "ok", "action": action, "running": _running}


@app.post("/api/control/speed")
def set_speed(req: SpeedRequest):
    global _speed
    _speed = max(0.1, min(10.0, req.speed))
    return {"status": "ok", "speed": _speed}


@app.post("/api/scheduler/algorithm")
def set_algorithm(req: AlgorithmRequest):
    try:
        kernel.set_algorithm(req.algorithm)
        return {"status": "ok", "algorithm": req.algorithm}
    except ValueError:
        return {"error": f"invalid algorithm {req.algorithm}"}


@app.post("/api/memory/policy")
def set_policy(req: PolicyRequest):
    try:
        kernel.set_memory_policy(req.policy)
        return {"status": "ok", "policy": req.policy}
    except ValueError:
        return {"error": f"invalid policy {req.policy}"}


@app.post("/api/process/spawn")
def spawn(req: SpawnRequest):
    from .kernel.process import ProcessType
    proc = kernel.spawn_process(
        name=req.name, ptype=ProcessType.USER, priority=req.priority,
        burst_time=req.burst_time, memory_required=req.memory_required, io_bound=req.io_bound,
    )
    return {"status": "ok", "pid": proc.pid}


@app.post("/api/process/{pid}/kill")
def kill(pid: int):
    ok = kernel.kill_process(pid)
    return {"status": "ok" if ok else "not_found", "pid": pid}


@app.post("/api/interrupt/{irq}")
def inject_interrupt(irq: str):
    kernel.inject_interrupt(irq)
    return {"status": "ok", "irq": irq.upper()}


@app.post("/api/memory/pressure")
def memory_pressure():
    kernel.trigger_memory_pressure()
    return {"status": "ok"}


@app.post("/api/workload")
def workload(count: int = 3):
    kernel.generate_workload(count)
    return {"status": "ok", "spawned": count}


@app.post("/api/chat")
def chat(req: ChatRequest):
    answer = kernel.ask_assistant(req.question)
    return {"question": req.question, "answer": answer}


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/")
def serve_dashboard():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


# ---------------------------------------------------------------- WS
@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    _connections.add(websocket)
    try:
        await websocket.send_text(json.dumps(kernel.snapshot()))
        while True:
            await websocket.receive_text()  # keep-alive / ignore inbound pings
    except WebSocketDisconnect:
        _connections.discard(websocket)
