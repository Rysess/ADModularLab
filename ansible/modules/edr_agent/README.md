# Module: `edr_agent`

Installs the Elastic Agent and enrols it into the lab's Fleet server.

## Requirements

| Key | Value |
| --- | ----- |
| `os` | `windows` |
| `min_instance_type` | `t3.small` |
| `requires_lab` | `edr_server` |

The agent is pulled from the `edr_server` host over HTTP, so its version
matches the running stack.

## Variables

| Variable | Default | Meaning |
| -------- | ------- | ------- |
| `edr_agent_workdir` | `C:\temp` | Download and unpack directory |
| `edr_agent_exe` | `C:\Program Files\Elastic\Agent\elastic-agent.exe` | Installed-agent probe |
| `edr_agent_kibana_port` | `5601` | Kibana port on the edr_server host |
| `edr_agent_fleet_port` | `8220` | Fleet server port on the edr_server host |
| `edr_agent_wait_retries` / `_delay` | `90` / `20` | Retry budget while the stack starts |
| `edr_agent_fleet_wait_timeout` | `900` | Seconds to wait for the Fleet server port |
| `edr_agent_excluded_dirs` | `[]` | Directories created and registered as Defend trusted-app entries |

Consumed from Terraform: `elastic_password`. From the inventory:
`elastic_private_ip`.

## Does

The module resolves one of three actions from the agent's state:

| Action | Condition |
| ------ | --------- |
| `install` | binary absent |
| `reinstall` | binary present, `elastic-agent status` reports not enrolled |
| `none` | already connected to Fleet |

`install` waits for the published archive, downloads and unpacks it, reads the
default enrollment token from the Kibana Fleet API and runs
`elastic-agent install --insecure`.

`reinstall` runs `elastic-agent uninstall -f` first. `elastic-agent enroll`
cannot repair an unenrolled agent in place; it exits non-zero with `the command
is executed as root but the program files are not owned by the root user`.

Both wait for the Fleet server port before enrolling.

## Exclusions

Empty by default: an agent monitors everything unless told otherwise. Any
directory listed is created on the host and registered against Defend's
`endpoint_trusted_apps` list, which is policy-agnostic, so the entry covers
every agent in the lab. A 409 from Kibana means the entry already exists and is
treated as unchanged.

```yaml
modules:
  - name: edr_agent
    vars:
      edr_agent_excluded_dirs: ['C:\excluded']
```

For a host without an EDR, use the `defender` module instead.

## Scope

The downloaded archive and its unpacked directory are left under
`edr_agent_workdir` after the install, about 1 GB. The enrollment token is
staged in `edr_agent_secret_dir`, which is created with an explicit ACL for
Administrators and SYSTEM only, and deleted by the script that reads it.

## Footprint

2 GB minimum, about 1 GB disk. Enrolment takes a couple of minutes once the
stack is up.
