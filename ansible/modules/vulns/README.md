# Module: `vulns`

Deliberate Active Directory misconfigurations, one toggle each. All off by
default.

## Requirements

| Key | Value |
| --- | ----- |
| `os` | `windows` |
| `min_instance_type` | `t3.medium` |
| `requires_role` | `dc` |

Installs `RSAT-AD-PowerShell`.

## Usage

```yaml
modules:
  - name: vulns
    vars:
      vulns_kerberoast: true
      vulns_asreproast: true
      vulns_dcsync: true
      vulns_dcsync_principals: [LabUser5]
```

Toggles decide what a host gets. Each scenario also carries its own tag
(`kerberoast`, `asreproast`, `unconstrained_delegation`, `rbcd`, `dcsync`).
Through `site.yml` the module include is tagged `modules`, so a scenario tag
selects nothing on its own — it excludes:

```
ansible-playbook site.yml --limit dc01 --tags modules
ansible-playbook site.yml --limit dc01 --tags modules --skip-tags dcsync
```

## Scenarios

| Toggle | Configures |
| ------ | ---------- |
| `vulns_kerberoast` | Service accounts with an SPN and a guessable password |
| `vulns_asreproast` | Existing users with Kerberos pre-authentication cleared |
| `vulns_unconstrained_delegation` | Computer accounts trusted for delegation to any service |
| `vulns_rbcd` | `msDS-AllowedToActOnBehalfOfOtherIdentity` on a target computer |
| `vulns_dcsync` | Replication extended rights on the domain naming context |

## Variables

| Variable | Default | Meaning |
| -------- | ------- | ------- |
| `vulns_kerberoast_accounts` | `svc_mssql`, `svc_web` | `{ sam, display, password, spn }` per account |
| `vulns_asreproast_users` | `[LabUser3, LabUser7]` | Existing accounts to clear pre-auth on |
| `vulns_unconstrained_delegation_computers` | `[]` | NetBIOS host names; `$` is appended |
| `vulns_rbcd_grants` | `[]` | `{ computer, allowed: [principal, ...] }` |
| `vulns_dcsync_principals` | `[]` | sAMAccountNames granted replication rights |

`vulns_asreproast_users` names accounts created by the `dc` role.
`vulns_unconstrained_delegation_computers` and `vulns_rbcd_grants` reference
computer accounts, which exist once those hosts have joined.

## Implementation

Kerberoast, unconstrained delegation and RBCD use `microsoft.ad.user` and
`microsoft.ad.computer`.

AS-REP roast uses `Set-ADAccountControl -DoesNotRequirePreAuth`, guarded on the
account's current value, so `userAccountControl` is not written wholesale.

DCSync reads the domain's `nTSecurityDescriptor`, adds the missing ACEs for
`DS-Replication-Get-Changes` and `DS-Replication-Get-Changes-All`, and writes
back once.

## Reversal

No `state: absent` path. Turn the toggle off and rebuild; turning it off on a
live lab leaves the existing configuration in place.

## Footprint

No resources beyond the domain controller. Under a minute.
