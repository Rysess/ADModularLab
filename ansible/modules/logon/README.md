# Module: `logon`

Who may log on to this host, and how.

## Requirements

| Key | Value |
| --- | ----- |
| `os` | `windows` |
| `min_instance_type` | `t3.small` |

Principals are resolved locally first, then in the domain, so domain groups are
written plainly. Prefix a local principal with `.\` or `BUILTIN\`.

## Variables

| Variable | Default | Meaning |
| -------- | ------- | ------- |
| `logon_admins` | `[]` | Added to local `Administrators` |
| `logon_rdp` | `[]` | Added to local `Remote Desktop Users` |
| `logon_interactive` | `[]` | `SeInteractiveLogonRight` |
| `logon_batch` | `[]` | `SeBatchLogonRight` |
| `logon_deny_interactive` | `[]` | `SeDenyInteractiveLogonRight` |
| `logon_deny_rdp` | `[]` | `SeDenyRemoteInteractiveLogonRight` |
| `logon_deny_network` | `[]` | `SeDenyNetworkLogonRight` |
| `logon_keep_administrators` | `true` | Keeps `BUILTIN\Administrators` in every allow list |

The module drives two different Windows mechanisms, and whether someone can log
on depends on how they interact:

- **Local group membership** (`logon_admins`, `logon_rdp`) is additive — names
  are added, never removed. `logon_rdp` grants no right by itself; it works
  because `Remote Desktop Users` carries `SeRemoteInteractiveLogonRight` under
  the default policy. So an RDP session needs membership here *and* no matching
  deny right.
- **User rights** (`logon_interactive`, `logon_batch`, the three `deny`s) are
  replaced outright, not merged: a right is left at its Windows default while
  its list is empty, and set to exactly the list once it is not. So
  `logon_interactive: [IT-Admins]` drops `BUILTIN\Users`, cutting off every
  ordinary domain user's console logon — that is the point, but the var name
  does not say "replace". `logon_keep_administrators` keeps
  `BUILTIN\Administrators` in these allow lists so you cannot lock the console.

Deny always beats allow. `logon_deny_network` covers WinRM and SMB, not just
interactive sessions, so denying it to the account Ansible connects as (the
local Administrator) leaves the host unreachable — preflight refuses that.
`logon_keep_administrators` protects allow lists only, never deny lists.

Together these express tiering:

```yaml
- name: srv-win01
  role: member
  domain: lab.local
  modules:
    - name: logon
      vars:
        logon_admins: [Server-Admins]        # local Administrators (additive)
        logon_rdp: [IT-Admins, Helpdesk]     # Remote Desktop Users (additive)
        logon_interactive: [Server-Admins]   # replaces the right; drops Users
        logon_deny_network: [Domain Admins]  # keep tier-0 off this tier-1 host
```

RDP still needs a path to 3389: either `expose_ports` on the host or the `vpn`
module in the lab. Preflight warns when neither is present.

On a controller there is no local SAM, so `Administrators` and
`Remote Desktop Users` are the domain's `BUILTIN` groups and the change is
forest-visible.

## Creates

Nothing. It edits local group membership and the local security policy.

## Footprint

Seconds. No reboot.
