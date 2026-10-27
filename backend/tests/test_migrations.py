import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]


def test_alembic_upgrade_matches_models(tmp_path):
    if os.environ.get("BM_TEST_DATABASE_URL"):
        pytest.skip("validado separadamente contra PostgreSQL")
    env = {"BM_ENVIRONMENT": "test", "BM_SECRET_KEY": "x" * 40, "BM_DATABASE_URL": f"sqlite:///{tmp_path / 'm.db'}",
           "PATH": ""}
    alembic = [sys.executable, "-m", "alembic"]
    up = subprocess.run([*alembic, "upgrade", "head"], cwd=BACKEND, env=env, capture_output=True, text=True)
    assert up.returncode == 0, up.stderr
    check = subprocess.run([*alembic, "check"], cwd=BACKEND, env=env, capture_output=True, text=True)
    assert check.returncode == 0, check.stdout + check.stderr
    down = subprocess.run([*alembic, "downgrade", "base"], cwd=BACKEND, env=env, capture_output=True, text=True)
    assert down.returncode == 0, down.stderr
