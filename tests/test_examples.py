from pathlib import Path

import pytest
from conftest import normalize

from labctl.config import load_yaml

EXAMPLES = sorted((Path(__file__).resolve().parent.parent / "examples").glob("*.yml"))


@pytest.mark.parametrize("path", EXAMPLES, ids=[p.stem for p in EXAMPLES])
def test_every_example_validates(path):
    r = normalize(load_yaml(path))
    assert r.ok, r.problems
