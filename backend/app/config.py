import os
from dataclasses import dataclass

@dataclass
class Settings:
    PROMETHEUS_URL: str = os.getenv("PROMETHEUS_URL", "http://prometheus:9090")
    BASELINE_MINUTES: int = int(os.getenv("BASELINE_MINUTES", "15"))
    RECENT_SECONDS: int = int(os.getenv("RECENT_SECONDS", "60"))
    STEP_SECONDS: int = int(os.getenv("STEP_SECONDS", "15"))
    Z_THRESHOLD: float = float(os.getenv("Z_THRESHOLD", "3.0"))
    Z_CRITICAL: float = float(os.getenv("Z_CRITICAL", "5.0"))
    CONSECUTIVE_POINTS: int = int(os.getenv("CONSECUTIVE_POINTS", "3"))
    MIN_BASELINE_POINTS: int = int(os.getenv("MIN_BASELINE_POINTS", "20"))
    DETECTION_INTERVAL_SECONDS: int = int(os.getenv("DETECTION_INTERVAL_SECONDS", "15"))
    RESOLVE_AFTER_CYCLES: int = int(os.getenv("RESOLVE_AFTER_CYCLES", "3"))
    MAX_ANOMALIES: int = int(os.getenv("MAX_ANOMALIES", "200"))

settings = Settings()
