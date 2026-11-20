"""Comment-preserving edits to a lab.yml (host add/rm, module add/rm)."""
import io
import re

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from .workspace import LabError


def _yaml():
    y = YAML()
    y.preserve_quotes = True
    y.indent(mapping=2, sequence=4, offset=2)
    y.width = 100
    return y


def load(path):
    y = _yaml()
    with open(path, encoding="utf-8") as fh:
        data = y.load(fh) or CommentedMap()
    return y, data


def dump(y, data):
    buf = io.StringIO()
    y.dump(data, buf)
    return buf.getvalue()


def _hosts(data):
    if "hosts" not in data or data["hosts"] is None:
        data["hosts"] = CommentedSeq()
    return data["hosts"]


def _find(data, name):
    """(host node, how) for a host name; how is 'list', 'map', 'count' or 'vpn'."""
    hosts = _hosts(data)
    items = hosts.items() if isinstance(hosts, dict) else \
        [(h.get("name"), h) for h in hosts if isinstance(h, dict)]
    for key, node in items:
        if key == name:
            return node, "map" if isinstance(hosts, dict) else "list"
    m = re.fullmatch(r"(.+?)(\d{2})", name)
    if m:
        for key, node in items:
            if key == m.group(1) and isinstance(node, dict) and node.get("count"):
                return node, "count"
    vpn = (data.get("lab") or {}).get("vpn")
    if vpn:
        vname = vpn.get("name", "vpn01") if isinstance(vpn, dict) else "vpn01"
        if name == vname:
            return None, "vpn"
    return None, None


def add_host(data, name, spec):
    node, _ = _find(data, name)
    if node is not None:
        raise LabError(f"host {name!r} already exists")
    hosts = _hosts(data)
    body = CommentedMap()
    for k, v in spec.items():
        if v not in (None, [], {}):
            body[k] = v
    if isinstance(hosts, dict):
        hosts[name] = body
    else:
        entry = CommentedMap([("name", name)])
        entry.update(body)
        hosts.append(entry)


def remove_host(data, name):
    node, how = _find(data, name)
    if how is None:
        raise LabError(f"no host named {name!r} in the lab")
    if how == "vpn":
        data["lab"]["vpn"] = False
        return f"lab.vpn turned off ({name} was the VPN host it adds)"
    if how == "count":
        base, idx = name[:-2], int(name[-2:])
        if idx != node["count"]:
            raise LabError(f"{name} is one of '{base}' (count: {node['count']}); only the "
                           f"last one, {base}{node['count']:02d}, can be removed this way. "
                           f"Edit lab.yml to restructure the group")
        if node["count"] > 1:
            node["count"] -= 1
            return f"'{base}' count lowered to {node['count']}"
        name = base
    hosts = _hosts(data)
    if isinstance(hosts, dict):
        del hosts[name]
    else:
        for i, h in enumerate(hosts):
            if isinstance(h, dict) and h.get("name") == name:
                del hosts[i]
                break
    return None


def _module_names(mods):
    if isinstance(mods, dict):
        return list(mods.keys())
    names = []
    for e in mods or []:
        if isinstance(e, str):
            names.append(e)
        elif isinstance(e, dict):
            names.append(e["name"] if "name" in e else next(iter(e)))
    return names


def add_module(data, host, module, mvars):
    node, how = _find(data, host)
    if node is None:
        raise LabError(f"no editable host named {host!r}"
                       + (" (it comes from lab.vpn; edit lab.yml)" if how == "vpn" else ""))
    note = f"applies to every host of '{host[:-2]}' (count)" if how == "count" else None
    mods = node.get("modules")
    if mods is None:
        mods = node["modules"] = CommentedSeq()
    if module in _module_names(mods):
        raise LabError(f"{host} already runs {module}; edit its settings in lab.yml")
    if isinstance(mods, dict):
        mods[module] = CommentedMap(mvars) if mvars else None
    elif mvars:
        mods.append(CommentedMap([(module, CommentedMap(mvars))]))
    else:
        mods.append(module)
    return note


def remove_module(data, host, module):
    node, how = _find(data, host)
    if node is None:
        raise LabError(f"no editable host named {host!r}")
    mods = node.get("modules")
    if module not in _module_names(mods):
        raise LabError(f"{host} does not run {module}")
    if isinstance(mods, dict):
        del mods[module]
    else:
        for i, e in enumerate(mods):
            n = e if isinstance(e, str) else (e.get("name") or next(iter(e)))
            if n == module:
                del mods[i]
                break
    return f"applies to every host of '{host[:-2]}' (count)" if how == "count" else None


def set_lab_key(data, key, value):
    if "lab" not in data or data["lab"] is None:
        data["lab"] = CommentedMap()
    data["lab"][key] = value
