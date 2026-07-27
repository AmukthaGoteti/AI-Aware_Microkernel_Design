# Deployment Guide

## 1. Local development (fastest path)

```bash
git clone <this-repo>
cd ai-microkernel-os/backend
python3 -m venv .venv && source .venv/bin/activate     # optional but recommended
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Open **http://localhost:8000** — the dashboard is served by the same process (see `serve_dashboard()` in `main.py`), so there is no separate frontend build or dev server to run.

To run from the repository root instead of inside `backend/`:
```bash
uvicorn backend.main:app --reload --port 8000 --app-dir .
```

## 2. Docker

`Dockerfile` (place at repo root):
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ backend/
COPY frontend/ frontend/
EXPOSE 8000
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Build and run:
```bash
docker build -t nova-microkernel .
docker run -p 8000:8000 nova-microkernel
```

`docker-compose.yml` (for future multi-service growth, e.g. adding a Postgres-backed metrics store):
```yaml
services:
  nova:
    build: .
    ports:
      - "8000:8000"
    restart: unless-stopped
```

## 3. Cloud deployment options

### Render / Railway / Fly.io (simplest managed option)
1. Connect the repository.
2. Build command: `pip install -r backend/requirements.txt`
3. Start command: `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`
4. Ensure the platform's port env var is respected (`--port $PORT`, not a hardcoded 8000).
5. WebSocket support must be enabled on the platform (all three support it by default; confirm no reverse proxy strips `Upgrade` headers).

### AWS (ECS Fargate or EC2)
1. Push the Docker image above to ECR.
2. Fargate task definition: 0.25 vCPU / 0.5 GB memory is comfortable headroom for this simulator (no GPU, no heavy ML runtime).
3. Put an Application Load Balancer in front with a WebSocket-compatible target group (ALB supports WS natively over HTTP/1.1 — no special config needed beyond idle-timeout ≥ 60s so long-lived WS connections aren't dropped).

### A note on scaling
The simulator currently keeps **all kernel state in a single in-process Python object** (`kernel` global in `main.py`). This is correct for a single-instance demo/portfolio deployment but does **not** horizontally scale — running multiple replicas behind a load balancer would give each replica its own independent simulation, and a client's WebSocket could reconnect to a different replica with different state. For a multi-instance production deployment, externalize `Kernel` state to Redis or a dedicated stateful service, or pin clients to a single instance (sticky sessions) as a stopgap.

## 4. Environment variables (suggested, not yet wired)

| Variable | Purpose | Default |
|---|---|---|
| `NOVA_TICK_INTERVAL` | Base seconds between ticks before speed multiplier | `0.5` |
| `NOVA_MEMORY_FRAMES` | Total physical frames simulated | `32` |
| `NOVA_DISK_BLOCKS` | Total filesystem blocks simulated | `256` |
| `NOVA_LOG_LEVEL` | Python logging level | `INFO` |

(Wiring these into `Kernel.__init__` / `_simulation_loop` is a small follow-up — currently these are hardcoded constants in `kernel.py` / `main.py`, called out here so a deployer knows where to look.)

## 5. Health checks

`GET /api/health` returns `{"status": "ok"}` and is suitable as a load-balancer/Kubernetes liveness probe. It does **not** currently check simulation-loop liveness (e.g. that ticks are actually advancing) — a stricter readiness probe would compare `tick` across two calls a few seconds apart.

## 6. Static asset caching

`frontend/index.html` pulls Chart.js and Google Fonts from public CDNs at runtime. For air-gapped or offline deployments, vendor these assets locally under `frontend/vendor/` and update the `<script src>` / `<link href>` paths accordingly.
