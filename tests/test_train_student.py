"""scripts/train_student.sh's own logic, with a stand-in for uvx (no MLX, no model, no download)."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "train_student.sh"

FAKE_UVX = r"""#!/bin/bash
# uvx --from SPEC CMD ARGS...: pretend to be mlx-lm. FAKE_BAD_TEMPLATE names a model whose template check fails.
shift 2
cmd="$1"; shift
echo "$cmd $*" >> "$FAKE_LOG"
case "$cmd" in
  python)
    if [[ "$2" == template && "$3" == "${FAKE_BAD_TEMPLATE:-}" ]]; then echo "MISMATCH between training and serving"; exit 1; fi ;;
  mlx_lm.lora)
    adapters=$(sed -n 's/^adapter_path: "\(.*\)"$/\1/p' "$2"); mkdir -p "$adapters"; touch "$adapters/adapters.safetensors" ;;
  mlx_lm.fuse|mlx_lm.convert)
    while [[ $# -gt 0 ]]; do [[ "$1" == --save-path || "$1" == --mlx-path ]] && mkdir -p "$2"; shift; done ;;
esac
exit 0
"""

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


def train(tmp_path: Path, lines: int = 100, **env) -> subprocess.CompletedProcess:
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    (data / "train.jsonl").write_text('{"messages": []}\n' * lines)
    (data / "valid.jsonl").write_text('{"messages": []}\n')
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "uvx").write_text(FAKE_UVX)
    (bin_dir / "uvx").chmod(0o755)
    full = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "FAKE_LOG": str(tmp_path / "uvx.log"),
            "OUT": str(tmp_path / "models" / "swarm-student-test"), **env}
    return subprocess.run(["bash", str(SCRIPT), str(data)], capture_output=True, text=True, env=full, timeout=60)


def test_the_run_says_how_long_training_will_take_before_it_starts(tmp_path):
    r = train(tmp_path, lines=1200)
    assert r.returncode == 0, r.stdout + r.stderr
    estimate = next(line for line in r.stdout.splitlines() if line.startswith("Estimated training time"))
    assert "1200 examples" in estimate and "3.5 s" in estimate and "~1.2 h" in estimate and "ITERS" in estimate
    assert r.stdout.index("Estimated training time") < r.stdout.index("Student ready")
    calls = (tmp_path / "uvx.log").read_text().splitlines()
    assert [c.split()[0] for c in calls] == ["python", "mlx_lm.lora", "mlx_lm.fuse", "mlx_lm.convert", "python", "python"]
    (tmp_path / "b").mkdir()
    r = train(tmp_path / "b", lines=1200, ITERS="120", SECS_PER_EXAMPLE="10")
    assert "120 examples" in r.stdout and "~20 min" in r.stdout


def test_a_fused_student_whose_template_differs_is_not_called_ready(tmp_path):
    out = tmp_path / "models" / "swarm-student-test"
    r = train(tmp_path, FAKE_BAD_TEMPLATE=str(out))
    assert r.returncode != 0
    assert out.is_dir()  # the model is saved, but flagged
    tail = r.stdout.strip().splitlines()[-2:]
    assert any("NOT ready" in line for line in tail), r.stdout
    assert "Student ready" not in r.stdout
