# Role: `dc`

Promotes the host into the first domain controller of a new forest and creates
the lab accounts. Applied to hosts with `role: dc`.

## Requirements

| Key | Value |
| --- | ----- |
| `os` | `windows` |
| `min_instance_type` | `t3.medium` |

The computer name is set by the `Set Windows computer names` play in
`site.yml`, before this role runs.

## Variables

| Variable | Default | Meaning |
| -------- | ------- | ------- |
| `dc_lab_user_count` | `10` | Number of `LabUser<n>` accounts |
| `dc_lab_user_prefix` | `LabUser` | Account name prefix |
| `dc_dns_servers` | `[127.0.0.1, {{ vpc_dns_ip }}, ::1]` | Resolver list, all address families |
| `dc_forest_mode` | `""` | Forest functional level; empty selects the default |
| `dc_domain_mode` | `""` | Domain functional level; empty selects the default |
| `dc_child_dc_display` | `Child Domain Promotion` | Display name of the child-domain promotion account |
| `dc_child_dc_groups` | `[Enterprise Admins, Domain Admins]` | Its group membership |
| `dc_child_dc_required` | computed | True when the lab holds a child of this domain |
| `dc_ad_retries` | `5` | Retries for the first directory writes after promotion |
| `dc_ad_delay` | `15` | Seconds between retries |

Consumed from Terraform: `domain_name`, `domain_admin_user`,
`domain_admin_display`, `domain_admin_pw`, `dsrm_password`,
`lab_user_password`, `vpc_dns_ip`.

## Creates

- A forest for `domain_name`, with AD DS, RSAT-ADDS and integrated DNS.
- `dc_lab_user_count` enabled users sharing `lab_user_password`.
- The lab domain admin, a member of `Domain Admins`.
- `svc_childdc`, an Enterprise Admin used by the `child_dc` role, created only
  when the lab holds a child of this domain.

Passwords use `update_password: on_create`.

## Footprint

4 GB minimum, 8 GB recommended. Promotion and reboot take 5-20 minutes.
