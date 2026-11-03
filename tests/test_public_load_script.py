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
