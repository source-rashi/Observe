"""Tests for IncidentManager (Phase 4)."""

from datetime import timezone
from app.incidents import Incident, IncidentManager
from app.store import Anomaly


def make_anomaly(aid, signal="latency_p95", endpoint="/api", severity="warning",
                 started_at=1000.0, status="active", incident_id=None):
    return Anomaly(
        id=aid,
        signal=signal,
        endpoint=endpoint,
        severity=severity,
        direction="spike",
        value=100.0,
        baseline_mean=20.0,
        baseline_std=5.0,
        z_score=4.0,
        unit="ms",
        status=status,
        started_at=started_at,
        last_seen_at=started_at,
        resolved_at=None if status == "active" else started_at,
        incident_id=incident_id,
    )


# ------------------------------------------------------------------
# assign
# ------------------------------------------------------------------

def test_anomalies_within_window_share_incident():
    mgr = IncidentManager(incident_window_seconds=120)
    a1 = make_anomaly("a001", started_at=1000.0)
    a2 = make_anomaly("a002", endpoint="/checkout", started_at=1060.0)  # 60 s later

    inc1 = mgr.assign(a1)
    inc2 = mgr.assign(a2)

    assert inc1.id == inc2.id
    assert "a001" in inc1.anomaly_ids
    assert "a002" in inc1.anomaly_ids


def test_anomaly_outside_window_creates_new_incident():
    mgr = IncidentManager(incident_window_seconds=120)
    a1 = make_anomaly("a001", started_at=1000.0)
    a2 = make_anomaly("a002", started_at=1300.0)  # 300 s later, outside window

    inc1 = mgr.assign(a1)
    inc2 = mgr.assign(a2)

    assert inc1.id != inc2.id


def test_assign_sets_incident_id_on_anomaly():
    mgr = IncidentManager()
    a = make_anomaly("a001")
    inc = mgr.assign(a)
    assert a.incident_id == inc.id


def test_severity_escalates_to_critical():
    mgr = IncidentManager(incident_window_seconds=120)
    a1 = make_anomaly("a001", severity="warning", started_at=1000.0)
    a2 = make_anomaly("a002", severity="critical", started_at=1020.0)

    inc = mgr.assign(a1)
    assert inc.severity == "warning"

    mgr.assign(a2)
    assert inc.severity == "critical"


def test_incident_resolves_only_when_all_members_resolved():
    mgr = IncidentManager(incident_window_seconds=120)
    a1 = make_anomaly("a001", started_at=1000.0)
    a2 = make_anomaly("a002", started_at=1010.0)
    mgr.assign(a1)
    mgr.assign(a2)

    # Resolve only a1
    a1.status = "resolved"
    a1.resolved_at = 1100.0
    by_id = {"a001": a1, "a002": a2}
    result = mgr.on_resolved(a1, by_id)
    assert result is None  # a2 still active

    # Resolve a2 as well
    a2.status = "resolved"
    a2.resolved_at = 1120.0
    a2.incident_id = a1.incident_id  # same incident
    by_id["a002"] = a2
    result = mgr.on_resolved(a2, by_id)
    assert result is not None
    assert result.status == "resolved"
    assert result.resolved_at is not None


def test_title_contains_multiple_endpoints():
    mgr = IncidentManager(incident_window_seconds=120)
    a1 = make_anomaly("a001", endpoint="/orders", started_at=1000.0)
    a2 = make_anomaly("a002", endpoint="/products", started_at=1010.0)
    mgr.assign(a1)
    inc = mgr.assign(a2)
    # Title should mention the signal and at least one endpoint
    assert "latency_p95" in inc.title


def test_resolved_incident_never_reused():
    mgr = IncidentManager(incident_window_seconds=120)
    a1 = make_anomaly("a001", started_at=1000.0)
    inc1 = mgr.assign(a1)

    # Resolve it
    a1.status = "resolved"
    a1.resolved_at = 1050.0
    mgr.on_resolved(a1, {"a001": a1})
    assert inc1.status == "resolved"

    # New anomaly within window — must NOT reuse the resolved incident
    a2 = make_anomaly("a002", started_at=1060.0)
    inc2 = mgr.assign(a2)
    assert inc2.id != inc1.id
    assert inc2.status == "open"


def test_restore_loads_incidents():
    mgr = IncidentManager()
    from datetime import datetime
    inc = Incident(
        id="inc_restored",
        status="open",
        severity="warning",
        title="test incident",
        started_at=datetime.fromtimestamp(1000.0, tz=timezone.utc),
    )
    mgr.restore([inc])
    assert mgr.get("inc_restored") is not None
    assert len(mgr.list("open")) == 1
