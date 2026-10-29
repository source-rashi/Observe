import asyncio
import random
from typing import List
from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/chaos", tags=["chaos"])

class ChaosState:
    def __init__(self):
        self.extra_latency_ms: int = 0
        self.error_rate: float = 0.0
        self.memory_leak: bool = False

state = ChaosState()
_leaked_memory_chunks: List[bytes] = []
MAX_LEAK_CHUNKS = 30  # 30 * 5 MB = 150 MB hard cap
CHUNK_5MB = 5 * 1024 * 1024

def is_chaos_active() -> bool:
    return state.extra_latency_ms > 0 or state.error_rate > 0.0 or state.memory_leak

async def apply_chaos() -> None:
    if state.extra_latency_ms > 0:
        await asyncio.sleep(state.extra_latency_ms / 1000.0)
    if state.error_rate > 0.0:
        if random.random() < state.error_rate:
            raise HTTPException(status_code=500, detail="Injected chaos error")

async def memory_leak_loop() -> None:
    while True:
        try:
            if state.memory_leak and len(_leaked_memory_chunks) < MAX_LEAK_CHUNKS:
                _leaked_memory_chunks.append(b"x" * CHUNK_5MB)
            await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            break
        except Exception:
            await asyncio.sleep(1.0)

@router.post("/latency")
async def set_latency(ms: int = Query(..., description="Latency in ms (0-5000)")):
    state.extra_latency_ms = max(0, min(5000, ms))
    return {"status": "ok", "extra_latency_ms": state.extra_latency_ms}

@router.post("/errors")
async def set_errors(rate: float = Query(..., description="Error rate (0.0-1.0)")):
    state.error_rate = max(0.0, min(1.0, rate))
    return {"status": "ok", "error_rate": state.error_rate}

@router.post("/memory-leak")
async def set_memory_leak(enabled: bool = Query(..., description="Enable or disable memory leak")):
    state.memory_leak = enabled
    return {
        "status": "ok",
        "memory_leak": state.memory_leak,
        "current_leaked_mb": len(_leaked_memory_chunks) * 5,
    }

@router.post("/reset")
async def reset_chaos():
    state.extra_latency_ms = 0
    state.error_rate = 0.0
    state.memory_leak = False
    _leaked_memory_chunks.clear()
    return {"status": "ok", "message": "Chaos state reset and leaked memory freed"}

@router.get("/status")
async def get_chaos_status():
    return {
        "extra_latency_ms": state.extra_latency_ms,
        "error_rate": state.error_rate,
        "memory_leak": state.memory_leak,
        "current_leaked_mb": len(_leaked_memory_chunks) * 5,
        "chaos_active": is_chaos_active(),
    }
