import yaml

from labctl import edit
from labctl.workspace import LabError

TEXT = """\
# my lab
lab:
  vpn: true   # keep me
hosts:
  dc01:
    role: dc
  ws:
    count: 3
"""


def load(tmp_path):
    p = tmp_path / "lab.yml"
    p.write_text(TEXT)
    return edit.load(p)


def test_add_and_remove_keep_comments(tmp_path):
    y, d = load(tmp_path)
    edit.add_host(d, "srv01", {"modules": ["shares"]})
    edit.add_module(d, "srv01", "logon", {"rdp": ["Helpdesk"]})
    out = edit.dump(y, d)
    assert "# my lab" in out and "# keep me" in out
    data = yaml.safe_load(out)
    assert data["hosts"]["srv01"]["modules"] == ["shares", {"logon": {"rdp": ["Helpdesk"]}}]
    edit.remove_module(d, "srv01", "shares")
    edit.remove_host(d, "srv01")
    assert "srv01" not in yaml.safe_load(edit.dump(y, d))["hosts"]


def test_count_groups_and_vpn_host(tmp_path):
    y, d = load(tmp_path)
    try:
        edit.remove_host(d, "ws01")
        raise AssertionError("only the last of a count group may go")
    except LabError:
        pass
    edit.remove_host(d, "ws03")
    assert d["hosts"]["ws"]["count"] == 2
    edit.remove_host(d, "vpn01")
    assert d["lab"]["vpn"] is False


def test_duplicates_are_refused(tmp_path):
    y, d = load(tmp_path)
    for fn in (lambda: edit.add_host(d, "dc01", {}), lambda: edit.add_module(d, "dc01", "x", {}) or
               edit.add_module(d, "dc01", "x", {})):
        try:
            fn()
            raise AssertionError("expected a refusal")
        except LabError:
            pass
