from app.config import Settings
from app.detector import Detection
from app.store import AnomalyStore

def make_detection(signal="latency_p95", endpoint="/products", z=4.0, val=120.0, ts=1000.0):
    return Detection(
        signal=signal,
        endpoint=endpoint,
        value=val,
        baseline_mean=20.0,
        baseline_std=5.0,
        z_score=z,
        severity="warning" if z < 5.0 else "critical",
        direction="spike" if z > 0 else "drop",
        detected_at=ts,
        points=[(ts, val)],
    )

def test_create_and_update_same_key():
    cfg = Settings(RESOLVE_AFTER_CYCLES=3)
    store = AnomalyStore(cfg)

    d1 = make_detection(z=3.5, val=50.0, ts=100.0)
    a1 = store.update(d1)
    assert a1.status == "active"
    first_id = a1.id
    assert a1.value == 50.0

    # Updating same (signal, endpoint) keeps same ID
    d2 = make_detection(z=6.0, val=80.0, ts=120.0)
    a2 = store.update(d2)
    assert a2.id == first_id
    assert a2.value == 80.0
    assert a2.severity == "critical"
    assert a2.last_seen_at == 120.0

def test_resolve_after_n_clear_cycles():
    cfg = Settings(RESOLVE_AFTER_CYCLES=3)
    store = AnomalyStore(cfg)

    d = make_detection()
    a = store.update(d)
    assert a.status == "active"

    # Cycle 1 clear
    store.mark_clear("latency_p95", "/products")
    assert a.status == "active"

    # Cycle 2 clear
    store.mark_clear("latency_p95", "/products")
    assert a.status == "active"

    # Cycle 3 clear -> resolved
    resolved = store.mark_clear("latency_p95", "/products")
    assert resolved is not None
    assert resolved.status == "resolved"
    assert resolved.resolved_at is not None

def test_reoccurrence_after_resolve_creates_new_anomaly():
    cfg = Settings(RESOLVE_AFTER_CYCLES=2)
    store = AnomalyStore(cfg)

    d1 = make_detection(ts=100.0)
    a1 = store.update(d1)
    id1 = a1.id

    store.mark_clear("latency_p95", "/products")
    store.mark_clear("latency_p95", "/products")
    assert a1.status == "resolved"

    # New detection for same signal+endpoint
    d2 = make_detection(ts=200.0)
    a2 = store.update(d2)
    assert a2.id != id1
    assert a2.status == "active"

def test_list_filtering():
    cfg = Settings(RESOLVE_AFTER_CYCLES=1)
    store = AnomalyStore(cfg)

    d1 = make_detection(endpoint="/e1")
    d2 = make_detection(endpoint="/e2")
    store.update(d1)
    a2 = store.update(d2)

    store.mark_clear("latency_p95", "/e2")
    assert a2.status == "resolved"

    actives = store.list("active")
    resolveds = store.list("resolved")
    alls = store.list("all")

    assert len(actives) == 1
    assert actives[0].endpoint == "/e1"
    assert len(resolveds) == 1
    assert resolveds[0].endpoint == "/e2"
    assert len(alls) == 2

def test_cap_on_max_anomalies():
    cfg = Settings(MAX_ANOMALIES=2, RESOLVE_AFTER_CYCLES=1)
    store = AnomalyStore(cfg)

    d1 = make_detection(endpoint="/e1", ts=10.0)
    store.update(d1)
    store.mark_clear("latency_p95", "/e1")  # resolved

    d2 = make_detection(endpoint="/e2", ts=20.0)
    store.update(d2)

    d3 = make_detection(endpoint="/e3", ts=30.0)
    store.update(d3)

    # Capacity is 2 -> resolved e1 should be dropped
    items = store.list("all")
    assert len(items) == 2
    endpoints = {a.endpoint for a in items}
    assert "/e1" not in endpoints
    assert "/e2" in endpoints
    assert "/e3" in endpoints
