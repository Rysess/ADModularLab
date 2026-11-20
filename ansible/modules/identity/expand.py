"""Expand the identity module's vars into an explicit directory.

Runs on the operator's machine (see labctl/config.py) before preflight, so the
users it generates can be named by other modules and checked. Deterministic: the
same lab name, domain and seed always yield the same people, and raising
`generate` appends users without reshuffling the existing ones.
"""
import random
import re
import unicodedata

FIRST = """
Aaron Adele Ahmed Aisha Alan Alice Amelia Anna Arthur Ava Benjamin Bianca Bruno
Camille Carlos Charlotte Chloe Daniel David Diane Dmitri Edward Elena Emily Emma
Ethan Fatima Felix Fiona Gabriel Grace Hannah Hugo Ines Isaac Ivan Jack James
Jasmine Julia Julien Karim Kate Laura Leo Liam Lucas Lucy Maria Marcus Maya Mia
Nadia Nathan Nina Noah Olivia Omar Oscar Paul Priya Rachel Raphael Sarah Sofia
Thomas Victor Yasmin Zoe
""".split()

LAST = """
Adams Alvarez Bailey Baker Bennett Bernard Brooks Carter Chen Clarke Collins Cooper
Davies Dubois Durand Edwards Evans Fischer Fontaine Garcia Gomez Green Hall Harris
Hughes Ivanova Jackson Johnson Kaur Kelly Khan King Klein Lambert Laurent Lee
Lefebvre Lewis Lopez Martin Meyer Mitchell Moreau Morgan Murphy Nguyen Novak Okafor
Patel Perez Petit Reed Richard Roberts Robinson Rossi Roux Schmidt Scott Silva
Simon Taylor Thompson Turner Walker Ward Weber Wilson Wright Young
""".split()

OFFICES = ["Paris", "London", "Berlin", "Madrid", "New York", "Lyon"]

# Weighted by headcount. `group` receives every member of the department; `head`
# is the title of its first hire, who becomes everyone else's manager.
DEPARTMENTS = [
    {"name": "Management", "group": "Management", "weight": 1,
     "head": "Chief Executive Officer", "titles": ["Chief Financial Officer",
                                                   "Chief Operating Officer", "Director"]},
    {"name": "Finance", "group": "Finance-Team", "weight": 3, "head": "Finance Director",
     "titles": ["Accountant", "Financial Analyst", "Payroll Specialist", "Controller"]},
    {"name": "HR", "group": "HR", "weight": 2, "head": "HR Director",
     "titles": ["HR Generalist", "Recruiter", "HR Business Partner"]},
    {"name": "IT", "group": "IT-Admins", "weight": 3, "head": "IT Manager",
     "titles": ["Systems Administrator", "Network Engineer", "Infrastructure Engineer"]},
    {"name": "Helpdesk", "group": "Helpdesk", "weight": 2, "head": "Service Desk Lead",
     "titles": ["Support Technician", "Service Desk Analyst"]},
    {"name": "DevOps", "group": "DevOps", "weight": 2, "head": "Head of Platform",
     "titles": ["DevOps Engineer", "Site Reliability Engineer"]},
    {"name": "Security", "group": "Security-Team", "weight": 1, "head": "CISO",
     "titles": ["Security Analyst", "SOC Analyst"]},
    {"name": "Sales", "group": "Sales-Team", "weight": 4, "head": "Sales Director",
     "titles": ["Account Executive", "Sales Manager", "Business Developer"]},
    {"name": "Marketing", "group": "Marketing-Team", "weight": 2, "head": "Marketing Director",
     "titles": ["Marketing Specialist", "Content Manager", "Brand Manager"]},
]

USER_KEYS = {"display", "description", "firstname", "surname", "email", "password",
             "enabled", "ou", "groups", "spn", "asrep", "sensitive", "department",
             "title", "company", "office", "phone", "manager"}
GROUP_KEYS = {"description", "scope", "category", "members", "ou"}


class _Err(Exception):
    pass


def _ascii(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _derived(name):
    """A per-account password, derived on the target from a Terraform secret.

    Unique per account (so owning one user does not hand you the next), stable
    across runs, and never written anywhere in clear on the operator side.
    """
    return "{{ domain_admin_pw | lab_derive('%s') }}" % name


def _user_spec(spec):
    if spec is None:
        return {}
    if isinstance(spec, str):
        return {"display": spec}
    if isinstance(spec, dict):
        return dict(spec)
    raise _Err(f"user value {spec!r} must be a display name or a mapping")


def _group_spec(spec):
    if spec is None:
        return {"members": []}
    if isinstance(spec, list):
        return {"members": list(spec)}
    if isinstance(spec, dict):
        out = dict(spec)
        out["members"] = list(out.get("members") or [])
        return out
    raise _Err(f"group value {spec!r} must be a member list or a mapping")


def _pick(rng, weighted):
    total = sum(d["weight"] for d in weighted)
    x = rng.uniform(0, total)
    for d in weighted:
        x -= d["weight"]
        if x <= 0:
            return d
    return weighted[-1]


def _unique_sam(base, taken):
    sam = base[:20].rstrip(".")
    n = 2
    while sam.lower() in taken:
        suffix = str(n)
        sam = base[:20 - len(suffix)].rstrip(".") + suffix
        n += 1
    taken.add(sam.lower())
    return sam


def expand(mv, ctx):
    try:
        return _expand(mv, ctx)
    except _Err as e:
        from labctl.config import ExpandError
        raise ExpandError(str(e)) from None


def _expand(mv, ctx):
    d = ctx.defaults
    get = lambda k: mv[k] if k in mv else d.get(k)  # noqa: E731
    domain = ctx.host["domain"]

    users = {}
    for sam, spec in (get("identity_users") or {}).items():
        users[str(sam)] = _user_spec(spec)
    groups = {}
    for name, spec in (get("identity_groups") or {}).items():
        groups[str(name)] = _group_spec(spec)
    ous = list(get("identity_ous") or [])

    def group(name, **kw):
        g = groups.setdefault(name, {"members": []})
        for k, v in kw.items():
            g.setdefault(k, v)
        return g

    def add_member(gname, member):
        g = group(gname)
        if member not in g["members"]:
            g["members"].append(member)

    if ("identity_users" in mv or "identity_groups" in mv) and "identity_generate" not in mv:
        ctx.warn(f"also generates {d.get('identity_generate')} staff on top of the declared "
                 f"accounts (the default); set generate: 0 for only yours")
    gen = get("identity_generate") or 0
    if isinstance(gen, dict):
        count, seed = int(gen.get("count", 0)), gen.get("seed")
    else:
        count, seed = int(gen), None
    seed = seed if seed is not None else get("identity_seed")
    if seed is None:
        seed = ctx.seed(domain)
    if count < 0 or count > 500:
        raise _Err("generate must be 0-500 users")

    company = get("identity_company") or (domain.split(".")[0].capitalize() + " Corp")
    root = get("identity_ou_root") or "Corp"
    taken = {u.lower() for u in users} | {"administrator", "guest", "krbtgt"}

    # -- generated staff -------------------------------------------------------
    generated = []   # (sam, dept) in hire order
    displays = {str(sp.get("display", u)).lower() for u, sp in users.items()}
    heads = {}
    for i in range(count):
        rng = random.Random(f"{seed}:{i}")
        first, last = rng.choice(FIRST), rng.choice(LAST)
        # A CN is unique per OU; re-draw rather than collide on "Alice Martin".
        while f"{first} {last}".lower() in displays:
            first, last = rng.choice(FIRST), rng.choice(LAST)
        displays.add(f"{first} {last}".lower())
        dept = _pick(rng, DEPARTMENTS)
        sam = _unique_sam(f"{_ascii(first)}.{_ascii(last)}", taken)
        is_head = dept["name"] not in heads
        if is_head:
            heads[dept["name"]] = sam
        title = dept["head"] if is_head else rng.choice(dept["titles"])
        spec = {
            "display": f"{first} {last}",
            "firstname": first,
            "surname": last,
            "email": f"{sam}@{domain}",
            "department": dept["name"],
            "title": title,
            "company": company,
            "office": rng.choice(OFFICES),
            "phone": f"+33 1 {rng.randint(40, 79)} {rng.randint(10, 99)} {rng.randint(10, 99)} {rng.randint(10, 99)}",
            "ou": f"{root}/Users/{dept['name']}",
            "password": _derived(sam),
        }
        if not is_head:
            spec["manager"] = heads[dept["name"]]
        users.setdefault(sam, spec)
        add_member(dept["group"], sam)
        generated.append((sam, dept["name"]))

    for dept in DEPARTMENTS:
        if dept["name"] in heads:
            group(dept["group"], ou=f"{root}/Groups",
                  description=f"All {dept['name']} staff")

    it_staff = [s for s, dept in generated if dept == "IT"]
    if it_staff:
        add_member("Server-Admins", it_staff[0])
        group("Server-Admins", ou=f"{root}/Groups", description="Tier 1 server administrators")

    # -- tiered admin accounts -------------------------------------------------
    n_admin = int(get("identity_admin_accounts") or 0)
    admins = []
    for sam in it_staff[:n_admin]:
        owner = users[sam]
        adm = _unique_sam(f"adm.{sam}", taken)
        users.setdefault(adm, {
            "display": f"{owner['display']} (Admin)",
            "description": f"Tier 0 account of {owner['display']}",
            "ou": "Tier0/Admins",
            "groups": ["Domain Admins"],
            "sensitive": False,
            "password": _derived(adm),
        })
        admins.append(adm)
        ctx.note(f"`{adm}` is a Domain Admin owned by `{sam}` ({owner['title']}).")

    # -- service accounts ------------------------------------------------------
    for sam, spec in (get("identity_service_accounts") or {}).items():
        spec = _user_spec(spec)
        spec.setdefault("ou", f"{root}/Service Accounts")
        spec.setdefault("password", _derived(sam))
        if "spn" in spec:
            spec["spn"] = [s.replace("{domain}", domain) for s in
                           (spec["spn"] if isinstance(spec["spn"], list) else [spec["spn"]])]
        users.setdefault(str(sam), spec)
        taken.add(str(sam).lower())

    # -- weaknesses on generated staff ------------------------------------------
    pool = [s for s, dept in generated if s not in heads.values()] or [s for s, _ in generated]
    rng = random.Random(f"{seed}:weak")
    order = rng.sample(pool, len(pool))

    weak = int(get("identity_weak_passwords") or 0)
    wordlist = list(get("identity_weak_password_list") or ["Summer2025!"])
    for i, sam in enumerate(order[:weak]):
        users[sam]["password"] = wordlist[i % len(wordlist)]
        ctx.note(f"`{sam}` has the sprayable password `{users[sam]['password']}`.")

    leak = int(get("identity_password_in_description") or 0)
    for sam in order[weak:weak + leak]:
        pw = f"Welcome{rng.randint(1000, 9999)}!"
        users[sam]["password"] = pw
        users[sam]["description"] = f"New starter - temporary password {pw}"
        ctx.note(f"`{sam}` keeps its password in its description (`{pw}`).")

    if count and (weak + leak) > len(pool):
        ctx.warn(f"only {len(pool)} generated users can carry a weakness; "
                 f"weak_passwords + password_in_description = {weak + leak}")

    # -- validate the final shape ----------------------------------------------
    for sam, spec in users.items():
        extra = set(spec) - USER_KEYS
        if extra:
            raise _Err(f"user {sam!r} has unknown keys {sorted(extra)}; "
                       f"expected {sorted(USER_KEYS)}")
        for k in ("groups", "spn"):
            if k in spec and isinstance(spec[k], str):
                spec[k] = [spec[k]]
        # A user's groups is sugar for the group's member list, which is what the
        # tasks apply; built-ins are populated without being recreated.
        for g in spec.pop("groups", []) or []:
            add_member(g, sam)
        if spec.get("spn"):
            ctx.note(f"`{sam}` has SPN {', '.join(spec['spn'])} (kerberoastable).")
        if spec.get("asrep"):
            ctx.note(f"`{sam}` does not require Kerberos pre-authentication (AS-REP roastable).")
    for name, spec in groups.items():
        extra = set(spec) - GROUP_KEYS
        if extra:
            raise _Err(f"group {name!r} has unknown keys {sorted(extra)}; "
                       f"expected {sorted(GROUP_KEYS)}")

    out = {k: v for k, v in mv.items()}
    out.update({
        "identity_users": users,
        "identity_groups": groups,
        "identity_ous": ous,
        # Read by other expanders (session's @admin); harmless to Ansible.
        "identity_generated_admins": admins,
    })
    for k in ("identity_password_policy", "identity_machine_account_quota"):
        v = get(k)
        if v not in (None, {}, ""):
            out[k] = v
    for k in ("identity_generate", "identity_seed", "identity_weak_passwords",
              "identity_weak_password_list", "identity_password_in_description",
              "identity_admin_accounts", "identity_service_accounts", "identity_company",
              "identity_ou_root"):
        out.pop(k, None)
    return out
