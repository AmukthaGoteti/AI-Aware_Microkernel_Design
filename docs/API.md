# API Reference

Base URL (local dev): `http://localhost:8000`

## REST endpoints

### `GET /api/state`
Full snapshot of current kernel state (same shape pushed over WebSocket). See [Snapshot shape](#snapshot-shape) below.

### `POST /api/control/{action}`
`action` ∈ `play | pause | step | reset`.
```bash
curl -X POST http://localhost:8000/api/control/pause
```
Response: `{"status": "ok", "action": "pause", "running": false}`

### `POST /api/control/speed`
Body: `{"speed": 2.0}` (clamped to 0.1–10.0).

### `POST /api/scheduler/algorithm`
Body: `{"algorithm": "AI" | "FCFS" | "SJF" | "ROUND_ROBIN" | "PRIORITY" | "MLQ"}`

### `POST /api/memory/policy`
Body: `{"policy": "LRU" | "FIFO" | "LFU" | "CLOCK"}`

### `POST /api/process/spawn`
Body:
```json
{
  "name": "batch_job",
  "priority": 5,
  "burst_time": 8,
  "memory_required": 4,
  "io_bound": false
}
```
Response: `{"status": "ok", "pid": 17}`

### `POST /api/process/{pid}/kill`
Response: `{"status": "ok", "pid": 17}` or `{"status": "not_found", "pid": 17}`

### `POST /api/interrupt/{irq}`
`irq` ∈ `KEYBOARD | DISK | NETWORK | SENSOR | DISPLAY | TIMER` (case-insensitive).

### `POST /api/memory/pressure`
No body. Forces several random page accesses across all live processes to induce faults/eviction for demo purposes.

### `POST /api/workload?count=4`
Spawns `count` randomized batch processes.

### `POST /api/chat`
Body: `{"question": "why is process 4 waiting?"}`
Response: `{"question": "...", "answer": "P4 (calculator) is READY, waiting for CPU allocation (3 ticks in queue). ..."}`

### `GET /api/health`
Liveness probe: `{"status": "ok"}`.

## WebSocket

### `WS /ws`
On connect, immediately sends one full snapshot, then pushes a new snapshot every simulated tick (rate controlled by `/api/control/speed`). The connection accepts (and ignores) any inbound text as a keep-alive ping.

```js
const ws = new WebSocket("ws://localhost:8000/ws");
ws.onmessage = (evt) => console.log(JSON.parse(evt.data).tick);
```

## Snapshot shape

```jsonc
{
  "tick": 1532,
  "algorithm": "AI",
  "quantum": 4,
  "running": { "pid": 12, "name": "ai_daemon", "state": "RUNNING", "ai_reason": "...", ... },
  "ready_queue": [ /* PCB dicts */ ],
  "blocked_queue": [ /* PCB dicts */ ],
  "processes": [ /* all non-terminated PCB dicts */ ],
  "cpu_utilization": 91.3,
  "cpu_history": [88.1, 90.2, ...],
  "memory": {
    "total_frames": 32, "used_frames": 21, "free_frames": 11,
    "page_faults": 340, "page_hits": 812, "fault_rate": 0.295,
    "prefetch_hits": 58, "swap_used": 12, "policy": "LRU",
    "frames": [ {"index":0,"pid":12,"page":3,"ref_bit":1,"use_count":4}, ... ],
    "recent_events": ["tick=1530 AI_PREFETCH pid=12 page=4 frame=9 (confidence=4/5)", ...],
    "fragmentation": 0.12
  },
  "ipc": { "pipes": 2, "shared_segments": 1, "pending_mail": {}, "recent_events": [...] },
  "interrupts": { "pending": 0, "total_handled": 4210, "timeline": [...], "prediction": {"irq":"TIMER","confidence":0.71,"reason":"..."} },
  "devices": { "keyboard": {"kind":"input","status":"idle","utilization":0.11}, ... },
  "filesystem": { "total_blocks":256, "used_blocks":34, "disk_usage_pct":13.3, "journal":[...], "tree": {...} },
  "security": { "current_mode":"user", "users": {"root":"root","user":"user"}, "audit_log":[...] },
  "network": { "open_sockets":[...], "queue_depth":0, "bandwidth_utilization":0.04, "recent_packets":[...] },
  "deadlock": { "cycle": null, "risk": {"risk":"low","trend":0.0,"message":"..."} },
  "ai": {
    "cpu_overload": {"ticks_until_overload": null, "message": "...", "predicted_value": 91.3, "confidence": 0.62},
    "memory_exhaustion": { ... },
    "starvation": [ {"pid":9,"name":"logger","waited":18,"message":"..."} ],
    "policy_recommendation": {"recommendation":"AI","reason":"...","current":"AI","changed":false},
    "memory_recommendation": {"recommendation":"...", "reason":"..."},
    "last_decision_reason": "P12 selected: predicted burst is shortest (4.2 ticks) ...",
    "health": {"score": 84.0, "verdict": "Fair — minor pressure detected"}
  },
  "metrics": { "avg_turnaround": 24.1, "avg_waiting": 15.7, "avg_response": 6.2, "throughput": 0.081 },
  "context_switches": 512,
  "boot_log": [ "POST: verifying simulated hardware descriptors", ... ]
}
```

## Error handling
All endpoints return HTTP 200 with an `{"error": "..."}` body for invalid enum values (e.g. unknown algorithm name) rather than raising a 500, so the dashboard can display the message without a try/catch around every fetch.
