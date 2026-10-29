import asyncio
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from app.routes import router as business_router
from app.chaos import router as chaos_router, memory_leak_loop
from app.metrics import record_request_metrics

@asynccontextmanager
async def lifespan(app: FastAPI):
    leak_task = asyncio.create_task(memory_leak_loop())
    yield
    leak_task.cancel()
    try:
        await leak_task
    except asyncio.CancelledError:
        pass

app = FastAPI(title="Demo App", lifespan=lifespan)

@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    raw_path = request.url.path
    if raw_path.startswith("/chaos"):
        return await call_next(request)

    start_time = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    except Exception:
        status_code = 500
        raise
    finally:
        duration_ms = (time.perf_counter() - start_time) * 1000.0
        route = request.scope.get("route")
        endpoint = route.path if route else raw_path
        record_request_metrics(endpoint, request.method, status_code, duration_ms)

app.include_router(business_router)
app.include_router(chaos_router)
