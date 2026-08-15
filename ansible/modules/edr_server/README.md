# Module: `edr_server`

Elastic Stack (Elasticsearch, Kibana, Fleet) in Docker, with the Windows and
Active Directory detection rules enabled and the matching Windows agent served
to the lab.

## Requirements

| Key | Value |
| --- | ----- |
| `os` | `linux` |
| `min_instance_type` | `t3.large` |

Needs outbound internet access. Give the host at least 100 GB of disk.

## Variables

| Variable | Default | Meaning |
| -------- | ------- | ------- |
| `edr_server_dir` | `/opt/elastic-container` | Checkout of the stack definition |
| `edr_server_repo` | `peasead/elastic-container` | Upstream stack definition |
| `edr_server_repo_version` | `main` | Pin to a tag or commit for reproducibility |
| `edr_server_agent_dir` | `/var/www/html/elastic-agent` | Where nginx serves the Windows agent |
| `edr_server_probe_container` | `ecp-elasticsearch` | Container the "already running" probe looks for |
| `edr_server_wait_retries` / `_delay` | `30` / `20` | Retry budget while the stack starts |
| `edr_server_rule_query` | Windows + AD tags | Which detection rules to enable |
| `edr_server_monitor_role` / `_user` | `version_reader` / `monitor` | Read-only Elasticsearch account |

Consumed from Terraform: `elastic_password`, `monitor_password`.

## Creates

- Docker CE, keyed with a `signed-by` keyring.
- The Elastic stack, with `elastic_password` substituted into `.env`.
- A trial licence and the Windows/AD detection rules. Both are advisory; a
  failure is reported but does not abort the run.
- nginx serving `elastic-agent-win.zip` at the stack's own version.
- A read-only `monitor` user.

## Notes

The checkout uses `update: false`. Substituting the password into the tracked
`.env` dirties the working tree, and a pull would refuse to run against it.
Bump `edr_server_repo_version` and remove the directory to move the pin.

`edr_server_repo` is third-party and tracked at `main` by default.

## Footprint

8 GB RAM minimum, 100 GB disk recommended. First run takes 20-30 minutes.
