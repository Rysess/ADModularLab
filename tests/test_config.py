from conftest import hosts, normalize


def test_inference_fills_os_role_domain_and_size():
    r = normalize({"hosts": {"dc01": {"role": "dc"}, "srv01": {}, "box": {"modules": ["vpn"]}}})
    assert r.ok, r.problems
    h = hosts(r)
    assert (h["dc01"]["os"], h["dc01"]["domain"]) == ("windows", "lab.local")
    assert (h["srv01"]["role"], h["srv01"]["domain"]) == ("member", "lab.local")
    assert (h["box"]["os"], h["box"]["role"]) == ("linux", "standalone")
    assert h["box"]["source_dest_check"] is False
    assert {"port": 1194, "proto": "udp"} in h["box"]["expose_ports"]


def test_sizes_rise_to_module_minimums():
    r = normalize({"hosts": {"dc01": {"role": "dc"}, "e": {"modules": ["edr_server"]}}})
    e = hosts(r)["e"]
    assert e["instance_type"] == "t3.large" and e["disk_gb"] == 100


def test_count_and_host_numbers_follow_the_network():
    r = normalize({"hosts": {"dc01": {"role": "dc", "ip": 10}, "ws": {"count": 3, "ip": 30}}}, index=42)
    h = hosts(r)
    assert h["dc01"]["private_ip"] == "10.42.1.10"
    assert [h[f"ws0{i}"]["private_ip"] for i in (1, 2, 3)] == ["10.42.1.30", "10.42.1.31", "10.42.1.32"]


def test_lab_vpn_adds_a_host_with_clients():
    r = normalize({"lab": {"vpn": {"clients": ["a", "b"]}}, "hosts": {}})
    vpn = hosts(r)["vpn01"]
    assert vpn["ansible_vars"]["vpn_clients"] == ["a", "b"]


def test_module_vars_take_their_prefix():
    r = normalize({"hosts": {"dc01": {"role": "dc"}, "s": {"modules": {"logon": {"rdp": ["X"]}}}}})
    assert hosts(r)["s"]["ansible_vars"]["logon_rdp"] == ["X"]


def test_spot_is_default_and_overridable():
    r = normalize({"hosts": {"dc01": {"role": "dc"}, "s": {"spot": False}}})
    h = hosts(r)
    assert h["dc01"]["spot"] is True and h["s"]["spot"] is False
    r = normalize({"lab": {"spot": False}, "hosts": {"dc01": {"role": "dc"}}})
    assert hosts(r)["dc01"]["spot"] is False


def test_problems_are_reported_not_raised():
    r = normalize({"lab": {"bogus": 1}, "hosts": {"x": {"ip": "10.0.1.5", "colour": "red"}}})
    text = "\n".join(r.problems)
    assert "bogus" in text and "colour" in text and "outside this lab's subnet" in text


def test_member_needs_a_domain_controller():
    r = normalize({"hosts": {"srv01": {"role": "member"}}})
    assert any("needs a domain controller" in p for p in r.problems)


def test_several_forests_need_an_explicit_domain():
    r = normalize({"hosts": {"a": {"role": "dc", "domain": "a.local"},
                             "b": {"role": "dc", "domain": "b.local"}, "m": {}}})
    assert any("several forests" in p for p in r.problems)


def test_durations():
    from labctl.config import parse_hours
    p = []
    assert [parse_hours(v, "x", p) for v in (8, "8h", "2d", "1w")] == [8, 8, 48, 168]
    parse_hours("soon", "x", p)
    assert p
