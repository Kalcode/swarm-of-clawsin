import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("public_load_test", Path(__file__).resolve().parent.parent / "scripts" / "public_load_test.py")
lt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lt)


def test_cputime_and_percentiles():
    assert lt.parse_cputime("1010:10.79") == pytest.approx(60610.79) and lt.parse_cputime("0:00.02") == pytest.approx(0.02)
    assert lt.parse_cputime("1:02:03") == pytest.approx(3723.0)
    assert lt.percentile([1, 2, 3, 4, 100], 0.5) == 3 and lt.percentile([], 0.95) == 0


def test_the_live_world_port_is_refused():
    with pytest.raises(SystemExit):
        lt.check_port(7777)


def phase(**kw):
    return {"tick_p95": 20.0, "ticks_per_s": 1.0, "errors": 0, "latency_p95_ms": 2.0, **kw}


def test_verdict_limits():
    base = phase()
    assert lt.verdict(base, phase(tick_p95=30.0))                       # base + 10
    assert not lt.verdict(base, phase(tick_p95=30.1))
    assert lt.verdict(phase(tick_p95=100.0), phase(tick_p95=125.0))     # 1.25 x base wins when larger
    assert not lt.verdict(phase(tick_p95=100.0), phase(tick_p95=125.1))
    assert not lt.verdict(base, phase(errors=1))
    assert not lt.verdict(base, phase(ticks_per_s=0.96)) and lt.verdict(base, phase(ticks_per_s=0.97))
    assert lt.verdict(base, phase(latency_p95_ms=50.0)) and not lt.verdict(base, phase(latency_p95_ms=50.1))


def test_a_phase_shorter_than_the_metrics_window_is_refused(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["public_load_test.py", "--seconds", "30"])
    with pytest.raises(SystemExit) as e:
        lt.main()
    assert e.value.code == 2 and "60" in capsys.readouterr().err
    monkeypatch.setattr("sys.argv", ["public_load_test.py", "--help"])
    with pytest.raises(SystemExit):
        lt.main()
    assert "last 60 s" in capsys.readouterr().out.replace("\n", " ")
