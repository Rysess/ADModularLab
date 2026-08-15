# Module: `laps`

Windows LAPS: per-host local Administrator passwords, rotated and stored in
Active Directory.

Legacy Microsoft LAPS (`ms-Mcs-AdmPwd`) is not used; its MSI is retired.
Windows LAPS is built into Server 2019+ with the April 2023 update.

## Requirements

| Key | Value |
| --- | ----- |
| `os` | `windows` |
| `min_instance_type` | `t3.small` |
| `requires_lab_role` | `dc` |

Applied to the hosts that should be LAPS-managed. Schema and permission work is
delegated to `laps_dc_host`; the policy is written locally.

`laps_dc_host` resolves to the DC serving this host's own domain, so a
multi-forest lab needs no pinning.

## Variables

| Variable | Default | Meaning |
| -------- | ------- | ------- |
| `laps_dc_host` | `{{ domain_dc_host }}` | DC serving this host's domain |
| `laps_managed_account` | `labadmin` | Local administrator LAPS rotates |
| `laps_target_ou` | `""` | Container holding managed computers; empty resolves to the domain's default computers container |
| `laps_password_age_days` | `30` | Rotation interval |
| `laps_password_length` | `20` | Generated password length |
| `laps_password_complexity` | `4` | 4 = upper, lower, digits, symbols |
| `laps_post_authentication_actions` | `3` | 3 = reset the password and log off the managed account |
| `laps_post_authentication_reset_delay_hours` | `24` | Grace period before that action |
| `laps_read_principals` | `[]` | Principals granted read of `msLAPS-Password` |

## Creates

- A local administrator named by `laps_managed_account`, added to
  `Administrators`.
- The `msLAPS-*` schema attributes, via `Update-LapsADSchema`.
- Computer self-write permission on the target container.
- The LAPS policy under `HKLM\Software\Microsoft\Policies\LAPS`, then a
  `Invoke-LapsPolicyProcessing` to force the first rotation.
- Read delegation for each principal in `laps_read_principals`.

## Misconfiguration

`laps_read_principals` is the toggle. Anything beyond Domain Admins can read
every local Administrator password in the container:

```yaml
modules:
  - name: laps
    vars:
      laps_read_principals:
        - Domain Users
```

Left empty, the module deploys a correctly configured LAPS.

## Managed account

LAPS rotates one local administrator, set by `AdministratorAccountName`. The
module points it at `laps_managed_account` and never at the built-in
Administrator, which is the account Ansible authenticates with: the first
rotation would otherwise change that password and lock the lab out of the host.

## Reading a password

```
Get-LapsADPassword -Identity SRV-WIN01 -AsPlainText
# -> Account: labadmin
```

## Scope

`Update-LapsADSchema` adds `msLAPS-*` to the forest schema. That is forest-wide
and cannot be undone; destroying the lab is the only way back. The task is
guarded on the attribute already existing, so it is a no-op after the first
managed host.

`requires_role: member` is deliberate. A domain controller has no local SAM, so
creating `laps_managed_account` there would create a *domain* account and add
it to the domain's Administrators.

## Footprint

No resources beyond the managed host. Under a minute.
