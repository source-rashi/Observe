import threading
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from app.config import Settings
from app.detector import Detection
from app.signals import SIGNALS

@dataclass
class Anomaly:
    id: str
    signal: str
    endpoint: str
    severity: str
    direction: str
    value: float
    baseline_mean: float
    baseline_std: float
    z_score: float
    unit: str
    status: str  # "active" | "resolved"
    started_at: float
    last_seen_at: float
    resolved_at: Optional[float]
    incident_id: Optional[str] = None
    points: List[Tuple[float, float]] = field(default_factory=list)


class AnomalyStore:
    def __init__(self, cfg: Settings):
        self.cfg = cfg
        self._lock = threading.Lock()
        self._anomalies: Dict[str, Anomaly] = {}          # id -> Anomaly
        self._active_keys: Dict[Tuple[str, str], str] = {}  # (signal, endpoint) -> anomaly_id
        self._clear_counts: Dict[Tuple[str, str], int] = {}  # (signal, endpoint) -> consecutive clear count
        self._signal_units = {s.name: s.unit for s in SIGNALS}
        self._events: List[Tuple[str, Anomaly]] = []      # (event_type, anomaly)

    # ------------------------------------------------------------------
    # Core mutation API (return values / signatures are unchanged)
    # ------------------------------------------------------------------

    def update(self, detection: Detection) -> Anomaly:
        key = (detection.signal, detection.endpoint)
        with self._lock:
            self._clear_counts[key] = 0
            if key in self._active_keys:
                anomaly_id = self._active_keys[key]
                anomaly = self._anomalies[anomaly_id]
                anomaly.value = detection.value
                anomaly.z_score = detection.z_score
                anomaly.severity = detection.severity
                anomaly.direction = detection.direction
                anomaly.last_seen_at = detection.detected_at
                anomaly.points = detection.points
                anomaly.baseline_mean = detection.baseline_mean
                anomaly.baseline_std = detection.baseline_std
                self._events.append(("updated", anomaly))
                return anomaly
            else:
                short_id = uuid.uuid4().hex[:8]
                unit = self._signal_units.get(detection.signal, "")
                anomaly = Anomaly(
                    id=short_id,
                    signal=detection.signal,
                    endpoint=detection.endpoint,
                    severity=detection.severity,
                    direction=detection.direction,
                    value=detection.value,
                    baseline_mean=detection.baseline_mean,
                    baseline_std=detection.baseline_std,
                    z_score=detection.z_score,
                    unit=unit,
                    status="active",
                    started_at=detection.detected_at,
                    last_seen_at=detection.detected_at,
                    resolved_at=None,
                    points=detection.points,
                )
                self._anomalies[short_id] = anomaly
                self._active_keys[key] = short_id
                self._events.append(("created", anomaly))
                self._enforce_capacity()
                return anomaly

    def mark_clear(self, signal: str, endpoint: str) -> Optional[Anomaly]:
        key = (signal, endpoint)
        with self._lock:
            if key not in self._active_keys:
                return None
            current_count = self._clear_counts.get(key, 0) + 1
            self._clear_counts[key] = current_count
            if current_count >= self.cfg.RESOLVE_AFTER_CYCLES:
                anomaly_id = self._active_keys.pop(key)
                self._clear_counts.pop(key, None)
                anomaly = self._anomalies.get(anomaly_id)
                if anomaly:
                    anomaly.status = "resolved"
                    anomaly.resolved_at = anomaly.last_seen_at
                    self._events.append(("resolved", anomaly))
                return anomaly
            return None

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def list(self, status: str = "active") -> List[Anomaly]:
        with self._lock:
            items = list(self._anomalies.values())
            if status == "all":
                return items
            return [a for a in items if a.status == status]

    def get(self, anomaly_id: str) -> Optional[Anomaly]:
        with self._lock:
            return self._anomalies.get(anomaly_id)

    # ------------------------------------------------------------------
    # Event bus
    # ------------------------------------------------------------------

    def pop_events(self) -> List[Tuple[str, Anomaly]]:
        """Return and clear pending lifecycle events.
        Each tuple is (event_type, anomaly) where event_type is one of
        'created', 'updated', 'resolved'.
        """
        with self._lock:
            ev = list(self._events)
            self._events.clear()
            return ev

    # ------------------------------------------------------------------
    # Restart recovery
    # ------------------------------------------------------------------

    def restore(self, anomalies: List[Anomaly]) -> None:
        """Load anomalies into the store without emitting events.
        Used on startup to re-hydrate state from the database.
        """
        with self._lock:
            for a in anomalies:
                self._anomalies[a.id] = a
                if a.status == "active":
                    key = (a.signal, a.endpoint)
                    self._active_keys[key] = a.id
                    self._clear_counts[key] = 0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _enforce_capacity(self) -> None:
        if len(self._anomalies) <= self.cfg.MAX_ANOMALIES:
            return

        to_drop = len(self._anomalies) - self.cfg.MAX_ANOMALIES
        resolved = sorted(
            [a for a in self._anomalies.values() if a.status == "resolved"],
            key=lambda x: x.resolved_at or 0.0,
        )

        dropped_count = 0
        for item in resolved[:to_drop]:
            del self._anomalies[item.id]
            dropped_count += 1

        if dropped_count < to_drop:
            remaining_to_drop = to_drop - dropped_count
            actives = sorted(
                [a for a in self._anomalies.values() if a.status == "active"],
                key=lambda x: x.started_at,
            )
            for item in actives[:remaining_to_drop]:
                del self._anomalies[item.id]
                key = (item.signal, item.endpoint)
                self._active_keys.pop(key, None)
                self._clear_counts.pop(key, None)
