import math
from dataclasses import dataclass
from typing import List, Optional, Tuple
from app.config import Settings
from app.signals import Signal

@dataclass
class Detection:
    signal: str
    endpoint: str
    value: float
    baseline_mean: float
    baseline_std: float
    z_score: float
    severity: str    # "warning" | "critical"
    direction: str   # "spike" | "drop"
    detected_at: float
    points: List[Tuple[float, float]]

def zscore(value: float, mean: float, std: float) -> float:
    if std <= 0.0:
        return 0.0
    return (value - mean) / std

def detect(
    signal: Signal,
    endpoint: str,
    points: List[Tuple[float, float]],
    now: float,
    cfg: Settings,
) -> Optional[Detection]:
    """Pure anomaly detection function using rolling baseline and z-scores."""
    cutoff = now - cfg.RECENT_SECONDS
    baseline = [p for p in points if p[0] < cutoff]
    recent = [p for p in points if p[0] >= cutoff]

    if len(baseline) < cfg.MIN_BASELINE_POINTS or len(recent) < cfg.CONSECUTIVE_POINTS:
        return None

    baseline_values = [p[1] for p in baseline]
    n = len(baseline_values)
    mean = sum(baseline_values) / n

    variance = sum((x - mean) ** 2 for x in baseline_values) / n
    raw_std = math.sqrt(variance)
    std = max(raw_std, signal.min_std)

    # Evaluate consecutive recent points
    check_points = recent[-cfg.CONSECUTIVE_POINTS:]
    is_anomalous_list = []
    z_scores = []

    for _, v in check_points:
        z = zscore(v, mean, std)
        z_scores.append(z)
        if signal.direction == "up":
            is_anomalous = (z >= cfg.Z_THRESHOLD)
        else:  # "both"
            is_anomalous = (abs(z) >= cfg.Z_THRESHOLD)
        is_anomalous_list.append(is_anomalous)

    if not all(is_anomalous_list):
        return None

    latest_point = check_points[-1]
    latest_val = latest_point[1]
    latest_z = z_scores[-1]

    severity = "critical" if abs(latest_z) >= cfg.Z_CRITICAL else "warning"
    direction = "spike" if latest_z > 0 else "drop"

    return Detection(
        signal=signal.name,
        endpoint=endpoint,
        value=latest_val,
        baseline_mean=mean,
        baseline_std=std,
        z_score=latest_z,
        severity=severity,
        direction=direction,
        detected_at=now,
        points=points[-20:],
    )
