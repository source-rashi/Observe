import asyncio
import random
from fastapi import APIRouter
from app.chaos import apply_chaos

router = APIRouter(tags=["business"])

@router.get("/health")
async def health():
    return {"status": "ok"}

@router.get("/products")
async def get_products():
    await apply_chaos()
    await asyncio.sleep(random.uniform(0.005, 0.020))
    return {
        "products": [
            {"id": "prod-1", "name": "Telemetry Agent", "price": 49.99},
            {"id": "prod-2", "name": "Metrics Visualizer", "price": 99.99},
            {"id": "prod-3", "name": "Anomaly Detector", "price": 149.99},
        ]
    }

@router.get("/orders")
async def get_orders():
    await apply_chaos()
    await asyncio.sleep(random.uniform(0.030, 0.080))
    return {
        "orders": [
            {"id": "ord-101", "total": 149.98, "status": "shipped"},
            {"id": "ord-102", "total": 49.99, "status": "processing"},
        ]
    }

@router.post("/checkout")
async def checkout():
    await apply_chaos()
    await asyncio.sleep(random.uniform(0.050, 0.150))
    return {
        "status": "success",
        "order_id": f"ord-{random.randint(1000, 9999)}",
        "message": "Checkout completed successfully",
    }
