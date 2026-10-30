from app.config import Settings
from app.detector import detect, zscore
from app.signals import Signal

def test_flat_baseline_plus_spike_detected():
    cfg = Settings(
        RECENT_SECONDS=60,
        MIN_BASELINE_POINTS=20,
        CONSECUTIVE_POINTS=3,
        Z_THRESHOLD=3.0,
        Z_CRITICAL=5.0,
    )
    sig = Signal("latency_p95", "fake_promql", "ms", "up", min_std=5.0, per_endpoint=True)

    now = 1000.0
    # 25 baseline points every 15s from now - 450s to now - 75s
    points = [(now - 450 + i * 15, 20.0) for i in range(25)]
    # 3 recent points with high spike (value 100.0 vs mean 20.0, min_std 5.0 -> z = 16.0)
    points.extend([(now - 45, 100.0), (now - 30, 100.0), (now - 15, 100.0)])

    res = detect(sig, "/checkout", points, now, cfg)
    assert res is not None
    assert res.signal == "latency_p95"
    assert res.endpoint == "/checkout"
    assert res.severity == "critical"
    assert res.direction == "spike"
    assert res.z_score >= 5.0

def test_stable_data_returns_none():
    cfg = Settings(MIN_BASELINE_POINTS=20, CONSECUTIVE_POINTS=3, Z_THRESHOLD=3.0)
    sig = Signal("latency_p95", "fake_promql", "ms", "up", min_std=5.0, per_endpoint=True)

    now = 1000.0
    # All stable around 20.0
    points = [(now - 450 + i * 15, 20.0) for i in range(25)]
    points.extend([(now - 45, 21.0), (now - 30, 20.5), (now - 15, 20.0)])

    res = detect(sig, "/checkout", points, now, cfg)
    assert res is None

def test_too_few_baseline_points():
    cfg = Settings(MIN_BASELINE_POINTS=20, CONSECUTIVE_POINTS=3, Z_THRESHOLD=3.0)
    sig = Signal("latency_p95", "fake_promql", "ms", "up", min_std=5.0, per_endpoint=True)

    now = 1000.0
    # Only 10 baseline points
    points = [(now - 200 + i * 15, 20.0) for i in range(10)]
    points.extend([(now - 45, 100.0), (now - 30, 100.0), (now - 15, 100.0)])

    res = detect(sig, "/checkout", points, now, cfg)
    assert res is None

def test_single_point_blip_ignored():
    cfg = Settings(MIN_BASELINE_POINTS=20, CONSECUTIVE_POINTS=3, Z_THRESHOLD=3.0)
    sig = Signal("latency_p95", "fake_promql", "ms", "up", min_std=5.0, per_endpoint=True)

    now = 1000.0
    points = [(now - 450 + i * 15, 20.0) for i in range(25)]
    # Only 1 high point, followed by normal
    points.extend([(now - 45, 100.0), (now - 30, 20.0), (now - 15, 20.0)])

    res = detect(sig, "/checkout", points, now, cfg)
    assert res is None

def test_direction_up_ignores_drops():
    cfg = Settings(MIN_BASELINE_POINTS=20, CONSECUTIVE_POINTS=3, Z_THRESHOLD=3.0)
    sig = Signal("latency_p95", "fake_promql", "ms", "up", min_std=5.0, per_endpoint=True)

    now = 1000.0
    points = [(now - 450 + i * 15, 50.0) for i in range(25)]
    # Big drop in latency
    points.extend([(now - 45, 5.0), (now - 30, 5.0), (now - 15, 5.0)])

    res = detect(sig, "/checkout", points, now, cfg)
    assert res is None

def test_direction_both_catches_drops():
    cfg = Settings(MIN_BASELINE_POINTS=20, CONSECUTIVE_POINTS=3, Z_THRESHOLD=3.0, Z_CRITICAL=5.0)
    sig = Signal("request_rate", "fake_promql", "req/s", "both", min_std=1.0, per_endpoint=True)

    now = 1000.0
    points = [(now - 450 + i * 15, 50.0) for i in range(25)]
    # Sharp drop
    points.extend([(now - 45, 2.0), (now - 30, 2.0), (now - 15, 2.0)])

    res = detect(sig, "/orders", points, now, cfg)
    assert res is not None
    assert res.direction == "drop"
    assert res.z_score < 0
    assert res.severity in ["warning", "critical"]

def test_std_floor_prevents_division_by_zero():
    cfg = Settings(MIN_BASELINE_POINTS=20, CONSECUTIVE_POINTS=3, Z_THRESHOLD=3.0)
    sig = Signal("memory_mb", "fake_promql", "MB", "up", min_std=5.0, per_endpoint=False)

    now = 1000.0
    # Zero variance baseline
    points = [(now - 450 + i * 15, 100.0) for i in range(25)]
    # Slight increase not exceeding min_std * Z_THRESHOLD (5 * 3 = 15)
    points.extend([(now - 45, 110.0), (now - 30, 110.0), (now - 15, 110.0)])

    res = detect(sig, "all", points, now, cfg)
    assert res is None  # 10 / 5.0 = 2.0 < 3.0 threshold

def test_critical_vs_warning_boundary():
    cfg = Settings(
        MIN_BASELINE_POINTS=20,
        CONSECUTIVE_POINTS=3,
        Z_THRESHOLD=3.0,
        Z_CRITICAL=5.0,
    )
    sig = Signal("latency_p95", "fake_promql", "ms", "up", min_std=10.0, per_endpoint=True)

    now = 1000.0
    points = [(now - 450 + i * 15, 50.0) for i in range(25)]
    # z = (85 - 50) / 10 = 3.5 (>= 3.0 warning, < 5.0 critical)
    points.extend([(now - 45, 85.0), (now - 30, 85.0), (now - 15, 85.0)])

    res = detect(sig, "/products", points, now, cfg)
    assert res is not None
    assert res.severity == "warning"
