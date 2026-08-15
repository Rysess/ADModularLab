# Role: `domain_member`

Renames the host and joins it to the lab domain in a single reboot. Applied to
hosts with `role: member`.

## Requirements

| Key | Value |
| --- | ----- |
| `os` | `windows` |
| `min_instance_type` | `t3.small` |
| `requires_lab_role` | `dc` |

## Variables

| Variable | Default | Meaning |
| -------- | ------- | ------- |
| `domain_member_dc_wait_timeout` | `1800` | Seconds to wait for LDAP on the DC |
| `domain_member_join_retries` | `5` | Retries for the join |
| `domain_member_join_delay` | `30` | Seconds between retries |

Consumed from Terraform: `domain_name`, `domain_admin_user`,
`domain_admin_pw`. From the inventory: `dc_private_ip`.

## Does

1. Asserts a `role_dc` host is in the inventory.
2. Points every adapter's DNS at the domain controller.
3. Waits for TCP/389 on the DC.
4. Sets the computer name and joins, in one `microsoft.ad.membership` call.

## Footprint

2 GB minimum. Join and reboot take about 5 minutes once the DC is up.
