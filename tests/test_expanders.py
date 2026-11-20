from conftest import hosts, normalize


def identity(r, host="dc01"):
    return hosts(r)[host]["ansible_vars"]


def test_identity_is_deterministic_and_grows_without_reshuffling():
    a = identity(normalize({"hosts": {"dc01": {"role": "dc", "modules": {"identity": {"generate": 10}}}}}))
    b = identity(normalize({"hosts": {"dc01": {"role": "dc", "modules": {"identity": {"generate": 14}}}}}))
    a_users = [u for u, s in a["identity_users"].items() if s.get("department")]
    b_users = [u for u, s in b["identity_users"].items() if s.get("department")]
    assert b_users[:len(a_users)] == a_users and len(b_users) == 14


def test_identity_weaknesses_and_unique_names():
    v = identity(normalize({"hosts": {"dc01": {"role": "dc", "modules": {"identity": {
        "generate": 60, "weak_passwords": 4, "password_in_description": 2, "admin_accounts": 2}}}}}))
    users = v["identity_users"]
    weak = [u for u, s in users.items() if s.get("password") in
            ("Summer2025!", "Winter2025!", "Welcome1!", "Password1!")]
    leaked = [u for u, s in users.items() if "temporary password" in s.get("description", "")]
    assert len(weak) == 4 and len(leaked) == 2
    displays = [(s.get("display"), s.get("ou")) for s in users.values()]
    assert len(displays) == len(set(displays))
    assert len(v["identity_generated_admins"]) == 2
    assert all(len(u) <= 20 for u in users)
    assert set(v["identity_generated_admins"]) <= set(v["identity_groups"]["Domain Admins"]["members"])


def test_identity_default_warns_when_only_explicit_accounts_are_meant():
    r = normalize({"hosts": {"dc01": {"role": "dc", "modules": {"identity": {"users": {"bob": "Bob"}}}}}})
    assert any("generate: 0" in w for w in r.warnings)


def test_shares_bots_can_read_their_share_and_defaults_need_identity():
    r = normalize({"hosts": {"dc01": {"role": "dc", "modules": ["identity"]}, "s": {"modules": ["shares"]}}})
    v = hosts(r)["s"]["ansible_vars"]
    it = next(x for x in v["shares_shares"] if x["name"] == "IT")
    assert "svc_backup" in it["read"]
    assert {b["kind"] for b in v["shares_bots"]} == {"script", "browse"}
    # Without identity the default loot/bots name accounts nobody creates: dropped.
    r = normalize({"hosts": {"dc01": {"role": "dc"}, "s": {"modules": ["shares"]}}})
    v = hosts(r)["s"]["ansible_vars"]
    assert v["shares_bots"] == [] and v["shares_loot"] == []


def test_shares_rejects_unknown_share_in_loot():
    r = normalize({"hosts": {"dc01": {"role": "dc"}, "s": {"modules": {"shares": {
        "loot": [{"kind": "note", "share": "Nope", "file": "x.txt", "user": "LabUser1"}]}}}}})
    assert any("Nope" in p for p in r.problems)


def test_session_admin_reference():
    r = normalize({"hosts": {"dc01": {"role": "dc", "modules": ["identity"]},
                             "ws": {"modules": {"session": {"user": "@admin"}}}}})
    assert r.ok, r.problems
    user = hosts(r)["ws"]["ansible_vars"]["session_users"][0]["user"]
    assert user.startswith("adm.")
    r = normalize({"hosts": {"dc01": {"role": "dc"}, "ws": {"modules": {"session": {"user": "@admin"}}}}})
    assert any("@admin" in p for p in r.problems)
