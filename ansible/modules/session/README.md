# Module: `session`

Seeds a live **interactive console session** for a domain user on this host: the
account shows up as a logged-on user (Task Manager's *Users* tab, `quser`,
`qwinsta`), holds a valid Kerberos TGT, and leaves its full credential set in
LSASS — a realistic "someone is signed in here" target for credential-theft
tooling (`sekurlsa::logonpasswords`, Rubeus, token impersonation, BloodHound
sessions).

## Requirements

| Key | Value |
| --- | ----- |
| `os` | `windows` |
| `min_instance_type` | `t3.small` |
| `requires_role` | `dc`, `child_dc` or `member` |
| `requires_lab_role` | `dc` |

The host must be domain-joined so it can log a domain user on and obtain a TGT,
so the module runs on a `dc`, `child_dc` or `member`, never a standalone box.
**Desktop Experience** (`windows_edition: full`, the default) gives the session
a real desktop; on `core` the logon still happens and is dumpable, but there is
no GUI to see it in.

## Variables

| Variable | Default | Meaning |
| -------- | ------- | ------- |
| `session_users` | `[]` | Exactly one entry: `{ user, password?, domain? }` |
| `session_wait_retries` / `session_wait_delay` | `18` / `10` | Post-reboot poll for the session + TGT |

`session_users` takes **one** entry — Windows has a single console, so one
interactive session per host; put further sessions on other hosts. The entry
needs a `user` (sAMAccountName). `password` defaults to the lab user password
(correct for the `LabUser*` accounts and any `identity` user without an explicit
password); `domain` defaults to this host's domain and only needs setting to log
on a user from another domain across a trust.

```yaml
- name: ws01
  role: member
  domain: lab.local
  modules:
    - name: session
      vars:
        session_users:
          - user: it.martin        # lab user password by default
```

To log a Domain Admin on (a juicy dump target on the DC), pass the account and
its password explicitly:

```yaml
- name: dc01
  role: dc
  domain: lab.local
  modules:
    - name: session
      vars:
        session_users:
          - user: john.john
            password: "{{ domain_admin_pw }}"   # the DA password from Terraform
```

## How it works

The module configures **Winlogon autologon** — `AutoAdminLogon`,
`DefaultDomainName`, `DefaultUserName`, `DefaultPassword` (plus `ForceAutoLogon`
so a logoff re-logs on, and no `AutoLogonCount` so it never expires) — and
reboots once. At boot the console logs the account on: a genuine **interactive
(type 2)** logon that caches the account's secrets in LSASS and requests a
Kerberos TGT. Because it is a real console session it appears in the *Users* tab
and `quser`, and it survives reboots.

`DefaultPassword` is stored in cleartext under the `Winlogon` key — deliberately;
it is itself a classic lab artifact — so the tasks that touch it are `no_log`.
On a domain controller the module also grants the account `SeInteractiveLogonRight`
(the Default Domain Controllers policy otherwise limits "Allow log on locally"
to admin groups); that grant is a local LSA edit a background Group Policy
refresh can reclaim after ~90 minutes on a DC, but a session already established
keeps its TGT. Running `session` on a member — the realistic placement — has no
such caveat.

Only one console session exists at a time. A trainee who RDPs in lands in a
*new* session, so the seeded "victim" session stays put as the target.

## Verification

After the reboot the module confirms, as `SYSTEM`, that the account is on a WTS
session (`quser`) *and* that its logon session has a `krbtgt` ticket
(`klist -li <luid>`), polling briefly and failing the play if either is missing
— so a wrong password surfaces here rather than leaving a dead autologon. Unlike
a batch or service logon, this session is visible to `query user` / `qwinsta`
and the Task Manager *Users* tab.

## Creates

Winlogon autologon registry values and the interactive logon session they
produce. No AD objects — the user must already exist (the `dc` role's
`LabUser*`, or `identity` / `vulns` accounts). To undo it, clear the `Winlogon`
`AutoAdminLogon`/`Default*` values and reboot; turning the module off in
`lab.yml` does not.

## Footprint

One always-on console logon. Seconds to apply, plus one reboot.
