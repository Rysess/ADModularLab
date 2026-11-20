# Module: `identity`

A populated, realistic directory: generated staff with departments, titles,
managers, offices and OUs; service accounts; separate admin accounts; and the
everyday weaknesses (sprayable and leaked passwords, SPNs, missing pre-auth)
that make a domain worth attacking. On top of that, an explicit `users` /
`groups` / `ous` layer declares exactly the accounts a scenario needs.

## Requirements

| Key | Value |
| --- | ----- |
| `os` | `windows` |
| `min_instance_type` | `t3.medium` (`t3.small` on Core) |
| `requires_role` | `dc` or `child_dc` |

It runs on the controller of the domain it fills (a `child_dc` fills its child
domain), in its own play ahead of every other module. So `logon`, `shares`,
`acl` and `session` on any host can use the accounts it creates.

## Quick start

```yaml
dc01:
  role: dc
  modules:
    identity:                 # defaults: 30 staff, 4 service accounts, 1 admin
                              # account, 3 sprayable passwords, 1 leaked one
```

Every setting can be written without its `identity_` prefix:

```yaml
    identity:
      generate: 60
      admin_accounts: 2
      weak_passwords: 5
      password_in_description: 2
      password_policy: { min_length: 7, lockout_threshold: 0 }
      machine_account_quota: 0
      users:
        alice:
          display: Alice Martin
          groups: [Domain Admins]
          sensitive: true
      groups:
        Tier0-Admins: { scope: universal, ou: Tier0/Admins, members: [alice] }
```

## The generated organisation

`generate: N` creates N people across nine departments: Management, Finance, HR,
IT, Helpdesk, DevOps, Security, Sales and Marketing, weighted by realistic
headcount. Each person gets:

- a `first.last` login, display name, email, title, department, company,
  office and phone number
- an OU per department (`Corp/Users/<Dept>`) and membership of the department
  group (`Finance-Team`, `IT-Admins`, `Helpdesk`, `DevOps`, `Sales-Team` ...)
- a manager: the first hire of each department heads it and manages the rest
- **a password of its own**, derived on the target from a Terraform secret, so
  owning one account does not hand you the next

The result is deterministic. The same lab name and domain always produce the
same people, and raising `generate` adds people without reshuffling those
already there. Set `seed` (or `generate: {count: N, seed: X}`) to get a
different population.

| Setting | Default | What it adds |
| ------- | ------- | ------------ |
| `generate` | `30` | Generated staff; `0` turns generation off |
| `admin_accounts` | `1` | `adm.<user>` Domain Admin accounts for the first N IT staff, in `Tier0/Admins` |
| `weak_passwords` | `3` | Staff given a password from `weak_password_list` (spraying) |
| `weak_password_list` | `Summer2025!`, `Winter2025!`, `Welcome1!`, ... | The sprayable passwords, used in order |
| `password_in_description` | `1` | Staff whose description holds their "temporary" password |
| `service_accounts` | `svc_backup`, `svc_sql`, `svc_deploy`, `svc_monitor` | Accounts in `Corp/Service Accounts`, see below |
| `prune` | `false` | Delete managed users/groups no longer declared (see Re-runs) |
| `company` | `<Domain> Corp` | Company attribute |
| `ou_root` | `Corp` | Top OU for generated users and groups |

Weaknesses only ever land on ordinary staff, never on department heads or admin
accounts. The default service accounts are what the `shares` module's default
loot and bots use:

| Account | Notable |
| ------- | ------- |
| `svc_backup` | Member of `Backup-Admins` and **Backup Operators** (SeBackupPrivilege on the DC) |
| `svc_sql` | SPN `MSSQLSvc/sql01.<domain>:1433`: kerberoastable, strong password |
| `svc_deploy` | Member of `DevOps` |
| `svc_monitor` | Runs the `shares` monitoring bot |

## Explicit accounts

`users`, `groups` and `ous` declare exactly what a scenario needs, on top of the
generated organisation.

**Users** are keyed by sAMAccountName (the login, at most 20 characters). The
value is a display name, or a mapping of:

| Key | Meaning |
| --- | ------- |
| `display`, `firstname`, `surname`, `email`, `description` | Identity attributes |
| `title`, `department`, `company`, `office`, `phone` | Organisation attributes |
| `manager` | sAMAccountName of the manager |
| `ou` | `Parent/Child` path, created on demand |
| `groups` | Groups to join, built-ins included (`Domain Admins`, `Backup Operators`) |
| `password` | Defaults to a strong per-account password |
| `enabled` | `false` creates the account disabled |
| `spn` | One or a list: makes the account kerberoastable |
| `asrep` | `true` clears Kerberos pre-authentication (AS-REP roastable) |
| `sensitive` | `true` sets "account is sensitive and cannot be delegated" |

**Groups** map a name to a member list, or to a mapping of `members`,
`description`, `scope` (`global`, `domainlocal`, `universal`), `category`
(`security`, `distribution`) and `ou`. A member is a user or a group, named by
sAMAccountName. A group that already exists, including a built-in, is
populated and never recreated or re-scoped. Omitting `groups` keeps the default
ten-group chart (`Finance-Team`, `IT-Admins`, `Helpdesk` ... with one LabUser
each); giving `groups` replaces it.

**OUs** listed in `ous` are only needed when nothing else references them.

### Passwords

Accounts with no `password` get a strong password unique to the account. It is
derived on the target from the lab's domain-admin secret, so it never appears
on the operator side. The `LabUser1`-`LabUser10` accounts that the `dc` role
creates share the lab user password from `./lab creds`, and serve as the
assumed-breach foothold. Other modules that need an account's password (the
`shares` loot and bots, `session`) look it up the same way, so the credentials
they plant always work.

## Domain-wide settings

| Setting | Effect |
| ------- | ------ |
| `password_policy` | Default domain policy: `min_length`, `complexity`, `lockout_threshold`, `lockout_minutes`, `max_age_days`, `min_age_days`, `history`, `reversible` |
| `machine_account_quota` | `ms-DS-MachineAccountQuota` (Windows default 10; `0` blocks RBCD/noPac-style computer creation) |

Each one is left untouched unless set. Preflight refuses passwords shorter than
`min_length`, and warns when a low `lockout_threshold` would let spraying lock
out the lab.

## What you'll find

`./lab up` writes the planted weaknesses (sprayable users, leaked descriptions,
admin accounts, SPNs) to `labs/<lab>/walkthrough.md`. It is a spoiler file for
instructors.

## Re-runs

| Change | Converges |
| ------ | --------- |
| new users, groups, members, OUs; more `generate` | yes |
| display name, `ou`, attributes, `manager`, `spn`, `asrep`, `sensitive`, `enabled` | yes |
| password | only with `update_password: always` (default `on_create`) |
| removing a user, group or member | with `prune: true` (see below); otherwise nothing is deleted |
| removing an OU | no |

With `prune: true`, users and groups this module created that `lab.yml` no
longer declares are deleted, and undeclared members are taken out of those
groups. It only touches objects marked `adminDescription: adlab`, which the
module sets on everything it creates. Built-ins, the LabUsers and anything made
by hand are never touched. Lowering `generate` with prune on removes the
newest generated staff.

All users are created and updated in a single PowerShell call rather than one
WinRM round trip each. Passwords travel as a sensitive parameter, so errors
are shown but secrets are not.

## Footprint

About two minutes for the default population, with no reboot.
