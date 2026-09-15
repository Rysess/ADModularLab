# Module: `session`

Seeds a live logon session for one or more domain users on this host: each gets
a running session that holds a valid Kerberos TGT, exactly as if the user had
signed in. The credential material is then present in LSASS for the attacks that
depend on it (ticket theft, `sekurlsa`, delegation abuse, BloodHound sessions).

## Requirements

| Key | Value |
| --- | ----- |
| `os` | `windows` |
| `min_instance_type` | `t3.small` |
| `requires_role` | `dc`, `child_dc` or `member` |
| `requires_lab_role` | `dc` |

The host must be domain-joined — only then can it log a domain user on and get a
TGT — so the module runs on a `dc`, `child_dc` or `member`, never a standalone
box.

## Variables

| Variable | Default | Meaning |
| -------- | ------- | ------- |
| `session_users` | `[]` | Users to log on; `{ user, password?, domain? }` per entry |
| `session_keepalive_path` | `powershell.exe` | Keep-alive process image |
| `session_keepalive_arguments` | a `Start-Sleep` loop | Its arguments |
| `session_task_prefix` | `LabSession` | Task name prefix (`LabSession-<user>`) |
| `session_task_folder` | `\LabSessions` | Task Scheduler folder |
| `session_wait_retries` / `session_wait_delay` | `12` / `10` | TGT verification poll |

Each `session_users` entry needs a `user` (the sAMAccountName). `password`
defaults to the lab user password (correct for the `LabUser*` accounts and any
`identity` user without an explicit password); `domain` defaults to this host's
domain, and only needs setting to log on a user from another domain across a
trust.

```yaml
- name: srv-win01
  role: member
  domain: lab.local
  modules:
    - name: session
      vars:
        session_users:
          - user: LabUser1          # lab user password by default
          - user: alice
          - user: svc_sql           # identity user with a custom password
            password: Summer2025!
          - user: partneradmin      # a user from a trusted domain
            domain: partner.local
            password: Autumn2025!
```

## How it works

For each user the module registers a scheduled task under
`\LabSessions` that runs as `DOMAIN\user` with the password **stored**
(`logon_type: password`). A stored-password task makes Windows perform a real
interactive/batch logon with that credential — not an S4U logon, which would
produce no network credentials and no TGT. That logon caches the account's
secrets and requests a Kerberos TGT, which lands in the new logon session's
ticket cache.

The task's action is a keep-alive that sleeps in a loop, so the logon session
(and its TGT) stays resident in LSASS instead of being torn down when a
short-lived process exits. A `boot` trigger re-establishes the session after a
reboot; a `registration` trigger starts it the moment the task is created, and
the module also explicitly starts any task that is not already running, so a
re-run brings a killed session back.

A stored-password task logs the user on as a batch job, so the account needs
`SeBatchLogonRight`. A member server grants that implicitly when the task is
registered, but a domain controller does not — the Default Domain Controllers
policy fixes the right to `Administrators`, `Backup Operators` and
`Performance Log Users` — so the module grants it explicitly (additively, via
`win_user_right`) for every host role. Take care combining this with the
`logon` module: a `logon_deny_*` right, or a replaced `logon_batch` list that
excludes the user, will block the logon.

On a domain controller the grant is a local LSA edit that a background Group
Policy refresh can reclaim after ~90 minutes; a session already established
keeps its TGT, but a post-reboot re-logon would then need the grant reapplied
(re-run the module). Running `session` on a member server — the realistic
placement — has no such caveat.

## Verification

After starting the tasks the module maps each user to its logon session
(`Win32_LoggedOnUser` / `Win32_LogonSession`, as `sessions.sh` does) and runs
`klist -li <luid>` as `SYSTEM` to confirm a `krbtgt` ticket is cached. It polls
briefly because the ticket appears a moment after the logon, and fails the play
if a session or its TGT never shows up — a wrong password surfaces here rather
than silently leaving a dead task. `./sessions.sh` does not list these: a
stored-password task is a batch logon (type 4), not console or RDP.

## Creates

One scheduled task per user under `\LabSessions`, and the logon session each
keeps alive. No AD objects — the users must already exist (the `dc` role's
`LabUser*`, or `identity` / `vulns` accounts). Removing the module's effect
means deleting the tasks; turning it off in `lab.yml` does not.

## Footprint

One near-idle keep-alive process per user. Seconds to apply. No reboot.
