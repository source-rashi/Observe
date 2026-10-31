"""Additional Phase 4 tests for AnomalyStore (lifecycle events and restore).

These extend test_store.py without touching existing tests.
"""
from app.config import Settings
from app.detector import Detection
from app.store import Anomaly, AnomalyStore


def make_detection(signal="latency_p95", endpoint="/api", z=4.0, val=100.0, ts=1000.0):
    return Detection(
        signal=signal,
        endpoint=endpoint,
        value=val,
        baseline_mean=20.0,
        baseline_std=5.0,
        z_score=z,
        severity="warning" if z < 5.0 else "critical",
        direction="spike",
        detected_at=ts,
        points=[(ts, val)],
    )


def make_anomaly(aid="abc00001", signal="latency_p95", endpoint="/api", status="active",
                 started_at=1000.0, incident_id=None):
    return Anomaly(
        id=aid,
        signal=signal,
        endpoint=endpoint,
        severity="warning",
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


# -------------------------------------------------------------------
# Event emission tests
# -------------------------------------------------------------------

def test_create_emits_created_event():
    store = AnomalyStore(Settings())
    d = make_detection()
    a = store.update(d)
    events = store.pop_events()
    assert len(events) == 1
    etype, ev_anomaly = events[0]
    assert etype == "created"
    assert ev_anomaly.id == a.id


def test_update_emits_updated_event():
    store = AnomalyStore(Settings())
    store.update(make_detection(ts=1000.0))
    store.pop_events()  # clear create event

    store.update(make_detection(ts=1060.0, val=999.0))
    events = store.pop_events()
    assert len(events) == 1
    assert events[0][0] == "updated"


def test_resolve_emits_resolved_event():
    cfg = Settings(RESOLVE_AFTER_CYCLES=1)
    store = AnomalyStore(cfg)
    store.update(make_detection())
    store.pop_events()  # clear create

    resolved = store.mark_clear("latency_p95", "/api")
    assert resolved is not None
    events = store.pop_events()
    assert len(events) == 1
    assert events[0][0] == "resolved"
    assert events[0][1].status == "resolved"


def test_pop_events_clears():
    store = AnomalyStore(Settings())
    store.update(make_detection())
    first = store.pop_events()
    assert len(first) == 1
    second = store.pop_events()
    assert len(second) == 0


# -------------------------------------------------------------------
# Restore tests
# -------------------------------------------------------------------

def test_restore_loads_active_anomalies():
    store = AnomalyStore(Settings())
    a = make_anomaly()
    store.restore([a])

    # No events emitted
    assert store.pop_events() == []

    # Anomaly is queryable
    found = store.get(a.id)
    assert found is not None
    assert found.id == a.id
    assert found.status == "active"

    # Listed correctly
    actives = store.list("active")
    assert any(x.id == a.id for x in actives)


def test_restore_active_then_update_does_not_duplicate():
    """A restored active anomaly updated by detection stays the same object."""
    cfg = Settings()
    store = AnomalyStore(cfg)
    a = make_anomaly(aid="test0001", signal="latency_p95", endpoint="/api", started_at=1000.0)
    store.restore([a])
    store.pop_events()  # ensure no events from restore

    # Same (signal, endpoint) detection -> should update existing, not create new
    store.update(make_detection(ts=1060.0, val=200.0))
    events = store.pop_events()
    assert len(events) == 1
    assert events[0][0] == "updated"

    all_anomalies = store.list("all")
    ids = [x.id for x in all_anomalies]
    assert ids.count("test0001") == 1, "restore + update must not duplicate"


def test_restore_resolved_not_in_active_index():
    """Resolved anomalies restored do not pollute the active-key index."""
    store = AnomalyStore(Settings())
    resolved = make_anomaly(status="resolved")
    store.restore([resolved])

    # A new detection for same key should create a NEW anomaly (not update the resolved one)
    a_new = store.update(make_detection())
    assert a_new.id != resolved.id
    events = store.pop_events()
    assert events[0][0] == "created"
