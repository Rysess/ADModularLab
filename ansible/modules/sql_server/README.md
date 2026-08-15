# Module: `sql_server`

SQL Server Express, reachable over TCP, with a demo database and login.

## Requirements

| Key | Value |
| --- | ----- |
| `os` | `windows` |
| `min_instance_type` | `t3.medium` |

Needs the `chocolatey.chocolatey` collection and outbound internet access.

## Variables

| Variable | Default | Meaning |
| -------- | ------- | ------- |
| `sql_server_instance` | `SQLEXPRESS` | Instance name |
| `sql_server_database` | `LabApp` | Demo database |
| `sql_server_login` | `svc_labapp` | SQL login, password from `sql_password` |
| `sql_server_port` | `1433` | Static TCP port |
| `sql_server_packages` | `[sql-server-express, sqlserver-cmdlineutils]` | Chocolatey packages |
| `sql_server_workdir` | `C:\temp` | Scratch directory for staged secrets |
| `sql_server_start_timeout` | `300` | Seconds to wait for the instance to accept connections |

Consumed from Terraform: `sql_password`.

## Creates

- SQL Server Express and the command-line tools.
- TCP/IP enabled on a static port. Express ships with the protocol disabled and
  a dynamic port. The instance registry key is version-stamped
  (`MSSQL15`, `MSSQL16`, ...) and resolved through the Instance Names map.
- A Windows firewall rule for the port. Exposure is bounded by the security
  group, which permits only lab-internal and VPN traffic.
- `BUILTIN\Administrators` as a `sysadmin` login.
- The `LabApp` database and the `svc_labapp` login.

## Notes

Setup runs under `become` with a batch logon. A WinRM network logon token
cannot reach the machine key container, and setup fails encrypting its
configuration XML.

The Chocolatey package does not pass `/SQLSYSADMINACCOUNTS`, so the only
`sysadmin` after install is the account that ran setup. The grant task fixes
that and runs as `SYSTEM`.

## Footprint

4 GB minimum, about 8 GB disk. Install takes 10-15 minutes and may reboot.
