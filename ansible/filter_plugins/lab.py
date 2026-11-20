"""Filters shared by the lab's modules.

lab_derive    a strong per-account password derived from a Terraform secret
lab_password  the password a named account really has in this lab
"""
import hashlib
import string

_ALPHABET = string.ascii_letters + string.digits


def lab_derive(secret, name, length=18):
    """Deterministic, unguessable without `secret`, meets AD complexity.

    Alphanumeric only: these end up in PowerShell, batch files, XML and
    connection strings, and none of them should need escaping.
    """
    digest = hashlib.sha256(f"{secret}|{name}".encode()).digest()
    n = int.from_bytes(digest, "big")
    chars = []
    for _ in range(length - 3):
        n, i = divmod(n, len(_ALPHABET))
        chars.append(_ALPHABET[i])
    # One of each class, in fixed positions, so complexity never depends on luck.
    return ("K" + "".join(chars[:6]) + "q" + "".join(chars[6:]) + "7")[:length]


def lab_password(user, identity_users=None, default=None, admin_user=None, admin_pw=None):
    """Password of `user`: its identity entry, the lab domain admin, or the lab default."""
    user = str(user)
    bare = user.split("\\")[-1].split("@")[0]
    if admin_user and bare.lower() == str(admin_user).lower():
        return admin_pw
    for sam, spec in (identity_users or {}).items():
        if str(sam).lower() == bare.lower():
            if isinstance(spec, dict) and spec.get("password"):
                return spec["password"]
            break
    return default


class FilterModule:
    def filters(self):
        return {"lab_derive": lab_derive, "lab_password": lab_password}
