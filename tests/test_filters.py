import re

import lab


def test_derived_passwords_are_strong_and_stable():
    a = lab.lab_derive("secret", "alice")
    assert a == lab.lab_derive("secret", "alice") != lab.lab_derive("secret", "bob")
    assert len(a) == 18 and re.search("[A-Z]", a) and re.search("[a-z]", a) and re.search("[0-9]", a)
    assert lab.lab_derive("other", "alice") != a


def test_password_lookup():
    users = {"svc_sql": {"password": "P1"}, "bob": "Bob"}
    assert lab.lab_password("LAB\\svc_sql", users, "dflt") == "P1"
    assert lab.lab_password("bob", users, "dflt") == "dflt"
    assert lab.lab_password("John.John", {}, "d", "john.john", "DA") == "DA"
