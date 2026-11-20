"""session: shorthands for session_users.

    session: {user: alice}          one account
    session: {user: "@admin"}       the first Domain Admin identity generated
    session: {user: "@admin2"}      the second one
"""
import re


def expand(mv, ctx):
    from labctl.config import ExpandError
    out = dict(mv)
    user = out.pop("session_user", None)
    if user:
        entry = dict(user) if isinstance(user, dict) else {"user": str(user)}
        out["session_users"] = [entry]
    for e in out.get("session_users") or []:
        if not isinstance(e, dict) or not e.get("user"):
            continue
        m = re.fullmatch(r"@admin(\d*)", str(e["user"]))
        if m:
            n = int(m.group(1) or 1)
            ident = ctx.module_vars("identity", e.get("domain")) or {}
            admins = ident.get("identity_generated_admins") or []
            if len(admins) < n:
                raise ExpandError(f"{e['user']} needs identity to generate at least {n} "
                                  f"admin account(s) (admin_accounts: {n}) in "
                                  f"{e.get('domain') or ctx.host['domain']}")
            e["user"] = admins[n - 1]
        ctx.note(f"`{e['user']}` is logged on interactively at the console "
                 f"(credentials and TGT in LSASS).")
    return out
