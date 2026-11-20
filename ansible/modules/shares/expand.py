"""Expand the shares module's vars: shares, loot, bots.

Normalises every short form into one explicit shape for the tasks, makes sure a
bot can read what it runs, and drops default loot/bots whose accounts this lab
does not create (so the module stays usable without the identity module).
"""
import re

KINDS = {"script", "batch", "config", "unattend", "note", "env", "gpp", "file"}
BOT_KINDS = {"script", "browse"}
SIGNING = {"default", "disabled", "required"}
SHARE_KEYS = {"read", "write", "full", "abe", "description", "path"}
LOOT_KEYS = {"share", "file", "kind", "user", "domain", "password", "content"}
BOT_KEYS = {"kind", "user", "domain", "share", "file", "every", "name"}
SHARE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,70}\$?$")


class _Err(Exception):
    pass


def _list(v):
    if v is None:
        return []
    return [str(x) for x in (v if isinstance(v, list) else [v])]


def expand(mv, ctx):
    try:
        return _expand(mv, ctx)
    except _Err as e:
        from labctl.config import ExpandError
        raise ExpandError(str(e)) from None


def _known_accounts(ctx, domain):
    """Accounts this lab creates in `domain`, or None when it cannot tell."""
    in_lab = any(h["role"] in ("dc", "child_dc") and h["domain"] == domain for h in ctx.hosts())
    if not in_lab:
        return None        # a domain outside the lab: cannot tell, assume it exists
    ident = ctx.module_vars("identity", domain) or {}
    names = {str(u).lower() for u in ident.get("identity_users", {})}
    names.add(ctx.cfg["lab"]["domain_admin"].lower())
    return names


def _exists(user, known):
    return known is None or user.lower() in known or re.match(r"(?i)^labuser\d+$", user)


def _expand(mv, ctx):
    d = ctx.defaults
    get = lambda k: mv[k] if k in mv else d.get(k)  # noqa: E731
    domain = ctx.host["domain"]

    # -- shares --------------------------------------------------------------
    raw = get("shares_shares") or {}
    if isinstance(raw, list):           # [{name, read, ...}] is accepted too
        raw = {s["name"]: {k: v for k, v in s.items() if k != "name"} for s in raw}
    shares = {}
    for name, spec in raw.items():
        name = str(name)
        if not SHARE_NAME_RE.match(name):
            raise _Err(f"share name {name!r} is not a valid SMB share name")
        if isinstance(spec, (str, list)):
            spec = {"read": spec}
        spec = dict(spec or {})
        extra = set(spec) - SHARE_KEYS
        if extra:
            raise _Err(f"share {name!r} has unknown keys {sorted(extra)}; "
                       f"expected {sorted(SHARE_KEYS)}")
        shares[name.lower()] = {
            "name": name,
            "dir": spec.get("path") or name.rstrip("$"),
            "read": _list(spec.get("read")),
            "write": _list(spec.get("write")),
            "full": _list(spec.get("full")),
            "abe": bool(spec.get("abe", False)),
            "description": str(spec.get("description", "")),
        }

    def share(name, where):
        s = shares.get(str(name).lower())
        if not s:
            raise _Err(f"{where} names share {name!r}, which is not defined here; "
                       f"known: {', '.join(x['name'] for x in shares.values()) or 'none'}")
        return s

    user_given = {k: k in mv for k in ("shares_loot", "shares_bots")}

    # -- loot ----------------------------------------------------------------
    loot = []
    for i, e in enumerate(get("shares_loot") or []):
        if not isinstance(e, dict):
            raise _Err(f"loot entry {e!r} must be a mapping")
        extra = set(e) - LOOT_KEYS
        if extra:
            raise _Err(f"loot entry {e!r} has unknown keys {sorted(extra)}")
        kind = e.get("kind", "note")
        if kind not in KINDS:
            raise _Err(f"loot kind {kind!r} must be one of {sorted(KINDS)}")
        if kind == "file":
            if "content" not in e:
                raise _Err("loot kind 'file' needs 'content'")
        elif not e.get("user"):
            raise _Err(f"loot entry {e!r} needs the 'user' whose credentials it leaks")
        if kind != "gpp" and not (e.get("share") and e.get("file")):
            raise _Err(f"loot entry {e!r} needs 'share' and 'file' (gpp goes to SYSVOL)")
        udom = e.get("domain") or domain
        user = str(e.get("user", ""))
        if user and "password" not in e and not _exists(user, _known_accounts(ctx, udom)):
            if not user_given["shares_loot"]:
                continue      # a default naming an account this lab does not make
            ctx.warn(f"loot for {user!r}: no such account is created in {udom}; "
                     f"it must already exist")
        entry = {"kind": kind, "user": user, "domain": udom,
                 "file": str(e.get("file", "")).replace("/", "\\")}
        if kind != "gpp":
            entry["share"] = share(e["share"], "loot")["name"]
        for k in ("password", "content"):
            if k in e:
                entry[k] = e[k]
        loot.append(entry)
        where = "SYSVOL (Groups.xml, MS14-025)" if kind == "gpp" else \
            f"\\\\{ctx.host['name']}\\{entry['share']}\\{entry['file']}"
        ctx.note(f"{kind} loot in {where} leaks the password of `{user}`." if user
                 else f"custom file at {where}.")

    # -- bots ----------------------------------------------------------------
    bots = []
    seen = set()
    for e in get("shares_bots") or []:
        if not isinstance(e, dict):
            raise _Err(f"bot entry {e!r} must be a mapping")
        extra = set(e) - BOT_KEYS
        if extra:
            raise _Err(f"bot entry {e!r} has unknown keys {sorted(extra)}")
        kind = e.get("kind")
        if kind not in BOT_KINDS:
            raise _Err(f"bot kind {kind!r} must be one of {sorted(BOT_KINDS)}")
        for k in ("user", "share", "file"):
            if not e.get(k):
                raise _Err(f"bot entry {e!r} needs {k!r}")
        udom = e.get("domain") or domain
        user = str(e["user"])
        if not _exists(user, _known_accounts(ctx, udom)):
            if not user_given["shares_bots"]:
                continue
            ctx.warn(f"bot runs as {user!r}, which this lab does not create in {udom}")
        s = share(e["share"], "bot")
        every = e.get("every", 5 if kind == "script" else 2)
        if not isinstance(every, int) or not 1 <= every <= 1440:
            raise _Err(f"bot 'every' {every!r} must be 1-1440 minutes")
        name = re.sub(r"[^A-Za-z0-9-]", "-", str(e.get("name") or f"{kind}-{user}"))
        if name.lower() in seen:
            raise _Err(f"two bots are named {name!r}; give one a 'name'")
        seen.add(name.lower())
        # The bot must be able to read what it runs or polls.
        principal = user if udom == domain else f"{udom.split('.')[0].upper()}\\{user}"
        if principal not in s["read"] + s["write"] + s["full"]:
            s["read"].append(principal)
        bots.append({"name": name, "kind": kind, "user": user, "domain": udom,
                     "share": s["name"], "file": str(e["file"]).replace("/", "\\"),
                     "every": every})
        writers = ", ".join(s["write"] + s["full"]) or "nobody (admins only)"
        unc = f"\\\\{ctx.host['name']}\\{s['name']}\\{bots[-1]['file']}"
        if kind == "script":
            ctx.note(f"`{user}` runs `{unc}` every {every} min; writable by {writers} "
                     f"-> code execution as `{user}`.")
        else:
            ctx.note(f"`{user}` connects to every UNC path listed in `{unc}` every "
                     f"{every} min; writable by {writers} -> NTLM capture/relay of `{user}`.")

    signing = get("shares_smb_signing") or "default"
    if signing not in SIGNING:
        raise _Err(f"smb_signing {signing!r} must be one of {sorted(SIGNING)}")
    if signing == "disabled":
        ctx.note(f"SMB signing is disabled on {ctx.host['name']} (NTLM relay target).")

    noise = get("shares_noise")
    if not isinstance(noise, int) or not 0 <= noise <= 200:
        raise _Err(f"noise {noise!r} must be 0-200 files per share")

    out = {k: v for k, v in mv.items()}
    out.update({
        "shares_shares": list(shares.values()),
        "shares_loot": loot,
        "shares_bots": bots,
        "shares_smb_signing": signing,
        "shares_noise": noise,
    })
    return out
