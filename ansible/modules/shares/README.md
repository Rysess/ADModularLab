# Module: `shares`

SMB shares of synthetic data behind per-group NTFS and share ACLs.

## Requirements

| Key | Value |
| --- | ----- |
| `os` | `windows` |
| `min_instance_type` | `t3.small` |
| `requires_lab_role` | `dc` |
| `requires_lab` | `identity` |

Group creation is delegated to the `role_dc` host; the rest runs locally. The
`identity` module fills those groups, so the ACLs are meaningless without it.

## Variables

| Variable | Default | Meaning |
| -------- | ------- | ------- |
| `shares_root` | `C:\Shares` | Filesystem root |
| `shares_netbios` | `{{ domain_netbios }}` | NetBIOS domain qualifying group names in ACLs |
| `shares_ad_groups` | 4 groups | Security groups the ACLs reference |
| `shares_definitions` | 5 shares | `{ name, grp }` mapping a share to its reader group |
| `shares_extra_dirs` | 3 paths | Deep and noisy directories |
| `shares_files` | 27 files | `{ dest, content }` written under `shares_root` |
| `shares_ad_retries` / `shares_ad_delay` | `5` / `10` | Retry budget for the delegated AD tasks |

## Creates

- The four AD security groups the shares are ACL'd to, if `identity` has not
  already created them.
- Five shares (`Finance`, `IT`, `Backups`, `DevOps`, `Public`), each readable
  only by its mapped group, NTFS inheritance disabled and inherited ACEs
  dropped.
- Synthetic keys, tokens, connection strings and backup blobs.

Every credential in `shares_files` is fabricated. The AWS keys are the values
from AWS documentation; the tokens are structurally valid and dead.

## Footprint

A few megabytes. About two minutes, mostly the per-file copies over WinRM.
