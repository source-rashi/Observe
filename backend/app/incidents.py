"""Incident grouping (pure in-memory, no I/O).

Grouping rule
-------------
A new anomaly joins an OPEN incident whose started_at is within
INCIDENT_WINDOW_SECONDS of the anomaly's started_at.  If no such
incident exists, a new one is opened.  A resolved incident is never
reused.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional


@dataclass
class Incident:
    id: str
    status: str             # "open" | "resolved"
    severity: str           # highest severity among anomalies
    title: str
    started_at: datetime
    resolved_at: Optional[datetime] = None
    last_seen_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    anomaly_ids: List[str] = field(default_factory=list)


SEVERITY_ORDER: Dict[str, int] = {"warning": 1, "critical": 2}


def _make_title(signal: str, endpoints: List[str]) -> str:
    """Generate a human-readable incident title."""
    direction_word = "spike"          # default; callers can override if needed
    if not endpoints or endpoints == ["all"]:
        return f"{signal} {direction_word}"
    unique_eps = sorted(set(endpoints))
    ep_str = ", ".join(unique_eps[:3])
    if len(unique_eps) > 3:
        ep_str += f" (+{len(unique_eps) - 3} more)"
    return f"{signal} {direction_word} on {ep_str}"


class IncidentManager:
    def __init__(self, incident_window_seconds: int = 120) -> None:
        self._incidents: Dict[str, Incident] = {}
        self._window = incident_window_seconds

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def assign(self, anomaly) -> Incident:
        """Assign *anomaly* to an open incident within the time window or
        create a new incident.  Sets ``anomaly.incident_id``."""
        a_started = datetime.fromtimestamp(anomaly.started_at, tz=timezone.utc)

        # Find a matching open incident (never reuse resolved ones)
        incident: Optional[Incident] = None
        for inc in self._incidents.values():
            if inc.status != "open":
                continue
            diff = abs((a_started - inc.started_at).total_seconds())
            if diff <= self._window:
                incident = inc
                break

        if incident is None:
            inc_id = f"inc_{uuid.uuid4().hex[:8]}"
            incident = Incident(
                id=inc_id,
                status="open",
                severity=anomaly.severity,
                title="",
                started_at=a_started,
                last_seen_at=a_started,
                anomaly_ids=[],
            )
            self._incidents[inc_id] = incident

        # Attach the anomaly
        if anomaly.id not in incident.anomaly_ids:
            incident.anomaly_ids.append(anomaly.id)
        incident.last_seen_at = a_started

        # Escalate severity
        if SEVERITY_ORDER.get(anomaly.severity, 0) > SEVERITY_ORDER.get(incident.severity, 0):
            incident.severity = anomaly.severity

        # Refresh title — caller must pass a dict of known anomalies or we
        # just use the signal/endpoint of the anomaly being assigned.
        incident.title = _make_title(anomaly.signal, [anomaly.endpoint])

        anomaly.incident_id = incident.id
        return incident

    def refresh(self, anomaly, all_anomalies_by_id: Optional[Dict] = None) -> Optional[Incident]:
        """Update last_seen and severity when an anomaly is updated."""
        inc_id = getattr(anomaly, "incident_id", None)
        if not inc_id:
            return None
        incident = self._incidents.get(inc_id)
        if not incident:
            return None
        incident.last_seen_at = datetime.fromtimestamp(anomaly.last_seen_at, tz=timezone.utc)
        if SEVERITY_ORDER.get(anomaly.severity, 0) > SEVERITY_ORDER.get(incident.severity, 0):
            incident.severity = anomaly.severity
        # Refresh title with all known endpoints if available
        if all_anomalies_by_id:
            eps = [
                all_anomalies_by_id[aid].endpoint
                for aid in incident.anomaly_ids
                if aid in all_anomalies_by_id
            ]
            if eps:
                incident.title = _make_title(anomaly.signal, eps)
        return incident

    def on_resolved(self, anomaly, all_anomalies_by_id: Dict) -> Optional[Incident]:
        """Mark incident resolved if all member anomalies are resolved."""
        inc_id = getattr(anomaly, "incident_id", None)
        if not inc_id:
            return None
        incident = self._incidents.get(inc_id)
        if not incident or incident.status == "resolved":
            return None
        for aid in incident.anomaly_ids:
            a = all_anomalies_by_id.get(aid)
            if a and a.status != "resolved":
                return None
        incident.status = "resolved"
        incident.resolved_at = datetime.fromtimestamp(
            anomaly.resolved_at or anomaly.last_seen_at, tz=timezone.utc
        )
        return incident

    # ------------------------------------------------------------------
    # Recovery
    # ------------------------------------------------------------------

    def restore(self, incidents: List[Incident]) -> None:
        self._incidents = {inc.id: inc for inc in incidents}

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def list(self, status: str = "open") -> List[Incident]:
        if status == "all":
            return list(self._incidents.values())
        return [inc for inc in self._incidents.values() if inc.status == status]

    def get(self, inc_id: str) -> Optional[Incident]:
        return self._incidents.get(inc_id)
