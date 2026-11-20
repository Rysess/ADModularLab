import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ansible" / "filter_plugins"))


@pytest.fixture
def labs(tmp_path, monkeypatch):
    """An empty labs/ directory, so tests never touch real workspaces."""
    import labctl.workspace as w
    monkeypatch.setattr(w, "LABS", tmp_path / "labs")
    monkeypatch.setenv("AWS_REGION", "eu-west-3")
    return tmp_path / "labs"


def normalize(raw, name="t", index=20):
    from labctl import config, preflight
    r = config.normalize(raw, name, index, "eu-west-3")
    if r.ok:
        p, w = preflight.run(r.cfg)
        r.problems += p
        r.warnings += w
    return r


def hosts(r):
    return {h["name"]: h for h in r.cfg["hosts"]}
