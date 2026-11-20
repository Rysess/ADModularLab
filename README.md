# AD Modular Lab

Config-driven Active Directory labs on AWS. A short `lab.yml` declares the hosts
and the modules each one runs. `./lab` expands it, validates it, builds it with
Terraform, configures it with Ansible, and keeps it in line with the file as you
edit it. Any number of labs can run side by side, each in its own network.

> Labs expose WinRM and SSH (and RDP, when the lab has no VPN) to the deploying
> machine's public IP only, and run deliberately weak AD configurations. Do not
> connect them to anything you care about. WinRM uses NTLM with message
> encryption: neither passwords nor traffic cross the internet in clear.

## Install

Needs Terraform >= 1.6, Python >= 3.9 and AWS credentials (`aws configure`).

```
python3 -m venv venv
venv/bin/pip install -r requirements.txt
venv/bin/ansible-galaxy collection install -r ansible/requirements.yml
```

`./lab` uses `venv/` automatically.

## Quick start

```
./lab                    # interactive builder, or:
./lab new corp           # labs/corp/lab.yml, from examples/starter.yml
./lab up corp            # ~25 minutes for a fresh lab
./lab creds corp         # passwords, IPs, VPN profile location
./lab down corp
```

`labs/corp/vpn/client1.ovpn` connects you to the lab. `labs/corp/walkthrough.md`
lists the attack paths the modules planted (spoilers).

## Building a lab interactively

```
./lab                 # or: ./lab build [lab]
```

Starts from an empty lab, or opens an existing one, and asks one thing at a
time: what kind of host (domain controller, member, child DC, standalone), its
OS, version and edition, how many, which modules (only those that fit the host
are offered, each with a one-line description), then the few settings that
matter for each module. Account and group settings are picked from the
principals the lab will actually create, including `@admin` for a generated
Domain Admin. Every list filters as you type, like Ctrl+R in a shell. The lab is
validated after each step, problems are shown in red, and the last menu saves
`labs/<lab>/lab.yml` or saves and deploys it. Editing an existing lab keeps its
comments.

## Writing a lab

```yaml
lab:
  domain: lab.local
  expires: 24h
  vpn: true

hosts:
  dc01:
    role: dc
    modules:
      identity:                       # a generated organisation
  srv01:
    modules:
      shares:                         # file server with real loot and bots
      logon: { rdp: [Helpdesk] }
  ws:
    count: 3                          # ws01, ws02, ws03
    modules:
      session: { user: "@admin" }     # a Domain Admin logged on at each
```

Anything you leave out is inferred:

| Left out | Inferred as |
| -------- | ----------- |
| `os` | `windows` for `dc` / `child_dc` / `member`; otherwise from the modules (`vpn` is Linux) |
| `role` | `member` for a Windows host when the lab has a controller |
| `domain` | `lab.domain`, or the only forest in the lab |
| `instance_type`, `disk_gb` | the largest minimum of the role and modules (an `edr_server` gets `t3.large` / 100 GB) |
| a VPN host | `lab.vpn: true` adds `vpn01` with its port and routing |
| module var prefixes | `logon: {rdp: [x]}` means `logon_rdp: [x]` |
| the network | a free `10.<n>.0.0/16` for this lab; `ip: 10` is host `.10` in it |

`./lab validate <lab>` shows what a file expands to; `--show` prints all of it.

### `lab`

| Key | Default | |
| --- | ------- | - |
| `region` | your AWS CLI region, else `eu-west-3` | |
| `domain` | `lab.local` | default domain for controllers and members |
| `admin` / `admin_display` | `lab.admin` | the lab's domain admin |
| `expires` | `24h` | `8h`, `2d`, `1w`; the lab is stopped or terminated after it |
| `expires_action` | `terminate` | or `stop` |
| `expires_enabled` | `true` | `false` deploys no expiry Lambda |
| `vpn` | off | `true`, or `{clients: [alice, bob], name, type, ip}` |
| `network` | auto | `10.<n>.0.0/16` or `<n>`; pin it if a VPN client must route to two labs that you created separately |
| `allow_from` | your public IP | CIDRs allowed to reach WinRM/RDP/SSH |
| `imdsv1_enabled` | `false` | |
| `spot` | `true` | spot instances (~65% cheaper for Windows); `false` for on-demand. A host may set its own `spot` |

`defaults` sets `windows_instance_type`, `linux_instance_type`,
`windows_disk_gb`, `linux_disk_gb`, `windows_version` (`2016`/`2019`/`2022`/`2025`),
`windows_edition` (`full`/`core`) and `ubuntu_release` for every host.

### Hosts

`hosts` is a mapping keyed by name (or a list of `{name: ...}`). A host takes
`role` (`dc`, `child_dc`, `member`, `standalone`), `os`, `domain`, `count`,
`ip`, `type`, `disk`, `version`, `edition`, `ami`, `ports` (`[3389, "1194/udp"]`),
`vars` (raw Ansible host vars) and `modules`. The long names (`instance_type`,
`private_ip`, `disk_gb`, `windows_version`, `windows_edition`, `expose_ports`)
work too.

A `child_dc` serves a child of its domain minus the first label, so
`child.lab.local` sits under `lab.local`. A second forest is another `dc` with
another `domain`, and members then say which one they join.

`modules` is a mapping (`identity:`, `logon: {rdp: [x]}`) or a list (`- gmsa`,
`- {logon: {rdp: [x]}}`, `- {name: logon, vars: {...}}`).

## Cost

Hosts run on **spot instances** by default: Windows `t3.medium` costs $0.023/h
instead of $0.066/h on-demand (eu-west-3). If AWS reclaims capacity the host
is *stopped*, not lost; it comes back with its disk on `./lab start`. When spot
capacity (or a new account's spot quota) runs out, `./lab up` launches the
remaining hosts on-demand instead of failing. Set `spot: false` on the lab or a
host to opt out; it applies to new and rebuilt hosts.

A stopped lab costs only its disks and the VPN address (about $0.02/h for the
starter). An expired lab (`expires_action: terminate`) also releases its
Elastic IP, so nothing keeps billing.

## How a deployment runs

Terraform builds everything in one apply. Windows hosts rename themselves, and
switch off Windows Update, during their first boot, before Ansible connects.
Ansible then runs one play in which every host follows its own pipeline:

- Linux hosts (VPN, Elastic) are configured straight away; they need no domain.
- A member installs its slow prerequisites (SQL Server, the CA roles) while its
  domain controller promotes, then joins as soon as that controller is ready.
- A child domain waits for its parent only, not for every forest.
- Modules start once every domain is populated and every host has joined.

Hosts wait for each other at explicit barriers, through marker files in
`labs/<lab>/.lab/run`. A host that fails, or becomes unreachable, releases its
waiters at once with its error instead of leaving them to time out. A module can take part by shipping
`tasks/prepare.yml`, which runs before the domain exists.

## Changing a running lab

Edit `labs/<lab>/lab.yml` and run `./lab up <lab>` again. It shows what changes
(hosts added, removed, rebuilt, modules gained or lost), asks before destroying
anything, and applies only the difference. Or let `./lab` make the edit; it
keeps your comments and validates before saving:

```
./lab host add corp ws04 -m session           # add a member, deploy it
./lab host rm corp ws04                       # leave the domain, destroy it
./lab module add corp srv01 logon 'rdp=[Domain Users]'
./lab module rm corp srv01 sql_server
./lab expire corp 48h                         # or: never
./lab rebuild corp srv01                      # recreate from scratch
./lab plan corp                               # what `up` would do
```

- A removed member's computer account and DNS records are deleted from its
  domain before the instance goes.
- Modules add configuration; removing one stops it being applied but does not
  undo it. `up` offers to rebuild such a host (`--rebuild-changed` does it
  unattended), and `./lab rebuild` gives a clean host at any time. Rebuilding a
  domain controller rebuilds its domain's members with it. `identity` can also
  delete what it no longer declares, with `prune: true`.
- `./lab snapshot` images every host and remembers the Windows Administrator
  password each image carries, which EC2 does not publish. Set `ami: <id>` on a
  host and `up` rebuilds it from that image.
- The expiry is kept across `up`s. `./lab expire` (or `up --extend 8h`) moves it
  without touching anything else, even if `lab.yml` has undeployed edits.

## Several labs at once

Each lab is self-contained in `labs/<name>/`: its Terraform state, inventory,
secrets, VPN profiles, credentials and logs. Each gets its own VPC
(`10.<n>.0.0/16`) and VPN client range (`172.16.<n>.0/24`), so you can stay
connected to several at once.

```
./lab up red blue purple      # in parallel, one log per lab
./lab list                    # every lab, its network, instance states, expiry
```

## Operating

| Command | |
| ------- | - |
| `./lab status <lab>` | hosts, their state and IPs, and edits not yet deployed |
| `./lab creds <lab>` | credentials and addresses |
| `./lab stop` / `start <lab>` | pause compute, keep disks; the VPN address is fixed, so profiles keep working |
| `./lab snapshot <lab>` | one AMI per host; set `ami:` on a host to rebuild from it |
| `./lab sessions <lab>` | who is logged on where |
| `./lab logs <lab> [-f]` | the latest run's full Terraform and Ansible output |
| `./lab up <lab> --no-infra --limit srv01 --tags modules` | re-provision only |

Every step can be repeated. If a run fails or is interrupted, run the same
command again. Terraform retries a failed apply once with a fresh plan.
Provisioning retries once (`--retries N`). Stopped instances are started before
provisioning. Only one operation runs on a lab at a time.

## Roles

| Role | |
| ---- | - |
| [`dc`](ansible/roles/dc/README.md) | Promotes a forest root; creates `LabUser1`-`10` and the domain admin |
| [`child_dc`](ansible/roles/domain_child/README.md) | Promotes a child domain |
| [`member`](ansible/roles/domain_member/README.md) | Joins the domain |
| `standalone` | Modules only |

## Modules

`./lab modules` lists them.

| Module | OS | Runs on | |
| ------ | -- | ------- | - |
| [`identity`](ansible/modules/identity/README.md) | windows | dc / child_dc | Generated organisation, service and admin accounts, weak passwords, password policy |
| [`shares`](ansible/modules/shares/README.md) | windows | domain-joined | Shares with real ACLs, real credential loot, GPP passwords, user-simulating bots |
| [`session`](ansible/modules/session/README.md) | windows | domain-joined | A live interactive logon (credentials and TGT in LSASS) |
| [`logon`](ansible/modules/logon/README.md) | windows | any | Local admins, RDP users, logon rights |
| [`acl`](ansible/modules/acl/README.md) | windows | dc | AD ACEs between principals (GenericAll, WriteDacl ...) |
| [`vulns`](ansible/modules/vulns/README.md) | windows | dc | Kerberoast, AS-REP, delegation, RBCD, DCSync toggles |
| [`gmsa`](ansible/modules/gmsa/README.md) | windows | dc | KDS root keys and gMSAs |
| [`adcs`](ansible/modules/adcs/README.md) | windows | any | Enterprise CA with ESC1/4/8/11 |
| [`laps`](ansible/modules/laps/README.md) | windows | member | Windows LAPS, optionally over-delegated |
| [`trust`](ansible/modules/trust/README.md) | windows | dc | Forest and external trusts |
| [`sql_server`](ansible/modules/sql_server/README.md) | windows | any | SQL Server Express with a demo database |
| [`defender`](ansible/modules/defender/README.md) | windows | any | Defender on/off, exclusions |
| [`edr_server`](ansible/modules/edr_server/README.md) | linux | any | Elastic Stack, Fleet, detection rules |
| [`edr_agent`](ansible/modules/edr_agent/README.md) | windows | any | Elastic Agent enrolment |
| [`vpn`](ansible/modules/vpn/README.md) | linux | any | OpenVPN, split tunnel into the lab |

Ready-made labs are in [`examples/`](examples/README.md), and
[`breach.yml`](examples/breach.yml) is a full assumed-breach scenario.

## Layout

- `lab`, `labctl/`: the CLI. `config.py` expands a lab file, `preflight.py` validates it
- `ansible/roles/`, `ansible/modules/`: structural roles and per-host modules
- `terraform/`: one configuration, applied once per lab with that lab's state
- `labs/<name>/`: a lab's workspace (only `lab.yml` is meant for version control)
- `examples/`: templates for `./lab new --from`

### Tests

```
venv/bin/pip install -r requirements-dev.txt
venv/bin/python -m pytest tests
```

These cover the expansion of lab files, preflight on every example, the module
expanders, the comment-preserving editor, the interactive builder (with a
scripted UI), plan parsing, and the cross-host barriers (with a real
`ansible-playbook` on localhost). They need no AWS account.

### Writing a module

Create `ansible/modules/<name>/tasks/main.yml`, and optionally `defaults/`,
`lab_meta.yml` (`os`, `min_instance_type`, `min_disk_gb`, `requires_role`,
`requires_lab_role`, `requires_lab`) and `README.md`. Nothing else needs to
change. An optional `expand.py` defining `expand(vars, ctx)` runs at validation
time. It can normalise short forms, generate data, and record walkthrough notes
with `ctx.note()`, as `identity` and `shares` do.

## Upgrading from `run.sh`

The shell scripts and the root `lab.yml` are gone. Destroy any lab deployed
with them from a checkout that still has them. Then move its definition to
`labs/<name>/lab.yml`, replacing full private IPs with host numbers
(`ip: 10`). `./lab` warns if `terraform/terraform.tfstate` still tracks
resources.
