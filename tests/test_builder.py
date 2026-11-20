import yaml

from labctl import builder


class FakeUI:
    """Answers prompts from a script; every answer must be one of the offered choices."""

    def __init__(self, answers):
        self.answers = list(answers)

    def _take(self, msg, offered):
        v = self.answers.pop(0)
        if offered is not None:
            for x in (v if isinstance(v, list) else [v]):
                assert x in offered, f"{msg!r}: {x!r} not offered ({offered})"
        return v

    def select(self, msg, choices, default=None):
        return self._take(msg, [c[1] for c in choices])

    def checkbox(self, msg, choices, checked=()):
        return self._take(msg, [c[1] for c in choices])

    def text(self, msg, default="", validate=None):
        v = self.answers.pop(0)
        v = default if v is ... else v
        err = validate(v) if validate else None
        assert err is None, f"{msg}: {v!r} rejected: {err}"
        return v

    def confirm(self, msg, default=True):
        return self.answers.pop(0)

    def echo(self, text=""):
        pass


def test_build_a_lab_from_nothing(labs):
    ui = FakeUI([
        "__new__", "wiz",
        "add", "dc", ..., ..., "2022", "full", ["identity"], "30", "3", "auto", "10",
        "add", "member", ..., "2022", "full", ..., ["shares", "session", "logon"],
        "@admin", ["Helpdesk"], [], "auto", "",
        "add", "standalone", "linux", ..., ..., [], "auto", "",
        "lab", "vpn", True, "alice,bob", "expires", "8h", "back",
        ("edit", "srv01"), ("settings", "shares"), "smb_signing", "disabled", "__back__", "back",
        "save", "quit",
    ])
    ws, outcome = builder.run_builder(None, ui=ui)
    assert outcome == "quit" and not ui.answers
    data = yaml.safe_load(ws.lab_file.read_text())
    assert data["lab"]["vpn"] == {"clients": ["alice", "bob"]}
    assert data["hosts"]["dc01"]["modules"] == {"identity": None}   # defaults not written
    srv = data["hosts"]["srv01"]["modules"]
    assert srv["session"] == {"user": "@admin"} and srv["shares"] == {"smb_signing": "disabled"}
    assert data["hosts"]["lin01"]["os"] == "linux"
    from labctl.cli import resolve
    assert resolve(ws, quiet=True).ok


def test_quitting_with_changes_asks(labs):
    ui = FakeUI(["__new__", "q", "add", "dc", ..., ..., "2022", "full", [], "auto", "",
                 "quit", False, "quit", True])
    ws, outcome = builder.run_builder(None, ui=ui)
    assert outcome == "quit" and not ws.lab_file.exists()
