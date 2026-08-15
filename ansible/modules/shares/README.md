# Module: `shares`

SMB shares of synthetic data behind per-group NTFS and share ACLs, plus the AD
groups those ACLs reference.

## Requirements

| Key | Value |
| --- | ----- |
| `os` | `windows` |
| `min_instance_type` | `t3.small` |
| `requires_lab_role` | `dc` |

AD group tasks are delegated to the `role_dc` host; the rest runs locally.

## Variables

| Variable | Default | Meaning |
| -------- | ------- | ------- |
| `shares_root` | `C:\Shares` | Filesystem root |
| `shares_netbios` | `{{ domain_netbios }}` | NetBIOS domain qualifying group names in ACLs |
| `shares_ad_groups` | 10 groups | Security groups to create |
| `shares_ad_group_members` | see defaults | Group membership |
| `shares_definitions` | 5 shares | `{ name, grp }` mapping a share to its reader group |
| `shares_extra_dirs` | 3 paths | Deep and noisy directories |
| `shares_files` | 27 files | `{ dest, content }` written under `shares_root` |
| `shares_ad_retries` / `shares_ad_delay` | `5` / `10` | Retry budget for the delegated AD tasks |

## Creates

- Ten AD security groups. `Auditors` is nested into `Finance-Team`,
  `IT-Admins`, `Backup-Admins`, `DevOps` and `Server-Admins`.
- Five shares (`Finance`, `IT`, `Backups`, `DevOps`, `Public`), each readable
  only by its mapped group, NTFS inheritance disabled and inherited ACEs
  dropped.
- Synthetic keys, tokens, connection strings and backup blobs.

Every credential in `shares_files` is fabricated. The AWS keys are the values
from AWS documentation; the tokens are structurally valid and dead.

## Footprint

A few megabytes. About two minutes, mostly the per-file copies over WinRM.
