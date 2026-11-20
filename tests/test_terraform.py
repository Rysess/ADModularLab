"""terraform fmt/validate. Plan-time errors need AWS and are not covered here."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

TF = Path(__file__).resolve().parent.parent / "terraform"
pytestmark = pytest.mark.skipif(not shutil.which("terraform"), reason="terraform not installed")


def run(*args, env=None):
    return subprocess.run(["terraform", *args], cwd=TF, capture_output=True, text=True,
                          env={**os.environ, **(env or {})}, timeout=300)


def test_formatted():
    assert run("fmt", "-check", "-recursive").returncode == 0


def test_valid(tmp_path):
    env = {"TF_DATA_DIR": str(tmp_path / "tf"),
           "TF_PLUGIN_CACHE_DIR": str(Path.home() / ".terraform.d" / "plugin-cache")}
    init = run("init", "-backend=false", "-input=false", env=env)
    if init.returncode != 0:
        pytest.skip(f"terraform init needs the providers: {init.stderr[-200:]}")
    v = run("validate", "-no-color", env=env)
    assert v.returncode == 0, v.stdout + v.stderr
