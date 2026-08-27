# AD Modular Lab

Config-driven Active Directory lab on AWS. A single `lab.yml` declares the hosts
and the modules each one runs. Terraform builds the infrastructure, Ansible
discovers it through the EC2 dynamic inventory and applies the modules. Access is
provided through an OpenVPN profile generated at deployment.

> The lab exposes WinRM, RDP and SSH to the deploying machine's public IP, and
> runs deliberately weak AD configurations. Do not connect it to anything you
> care about.

## Install

Needs Terraform >= 1.6, Python >= 3.9, AWS CLI v2 and `jq`.

```
python3 -m venv venv
. venv/bin/activate
pip install -r requirements.txt
ansible-galaxy collection install -r ansible/requirements.yml
```

## Quick setup

0. Define the hosts and modules in `lab.yml`
1. Setup credentials using `aws configure`
2. Run `./run.sh`
3. Import `ansible/client1.ovpn` into OpenVPN

Destroy with `./clean.sh`, pause with `./stop.sh` / `./start.sh`, snapshot with
`./snapshot.sh`, and list open sessions with `./sessions.sh`.

Ready-made definitions live in [`examples/`](examples/README.md); run one with
`LAB_FILE=examples/minimal.yml ./run.sh`. The default `lab.yml` costs about
**$0.20/hour** in `eu-west-3`.

## Configuration

Each host has an `os`, a `role`, the `domain` it belongs to, and a list of
`modules`.

```yaml
lab:
  name: ad-lab
  region: eu-west-3
  domain_admin: john.john

hosts:
  - name: dc01
    os: windows
    role: dc
    domain: lab.local
    private_ip: 10.0.1.10
    modules:
      - gmsa

  - name: srv-win01
    os: windows
    role: member
    domain: lab.local
    modules:
      - shares
```

`lab` takes `name`, `region` and `domain_admin` (required), plus optional
`domain_admin_display`, `expires_hours`, `expires_action`, `expires_enabled`.
`defaults` sets fleet-wide `windows_instance_type`, `linux_instance_type`,
`windows_disk_gb`, `linux_disk_gb`, `windows_version`, `windows_edition` and
`ubuntu_release`. A host may override any of these and also take `instance_type`,
`disk_gb`, `private_ip`, `ami`, `source_dest_check`, `expose_ports` and `vars`.
See [`examples/reference.yml`](examples/reference.yml) for every field annotated.

Every `dc`, `child_dc` and `member` names the domain it serves or joins. A
`child_dc` is a child of its domain minus the first label, so `child.lab.local`
sits under `lab.local`; a second forest is another `dc` with another `domain`.

`windows_version` is `2016`/`2019`/`2022`/`2025`. `windows_edition` is `full`
(Desktop Experience) or `core` (no desktop shell, smaller instances).

A `modules` entry is a bare name, or a mapping with a `vars` block for that
module on that host:

```yaml
modules:
  - shares
  - name: gmsa
    vars:
      gmsa_count: 6
```

`run.sh` validates `lab.yml` before Terraform runs; bypass with `./run.sh --force`.

## Roles

One per host, from the `role` field.

| Role | Description |
| ---- | ----------- |
| [`dc`](ansible/roles/dc/README.md) | Promotes the domain controller, creates users and a domain admin. |
| [`child_dc`](ansible/roles/domain_child/README.md) | Promotes a child domain beneath a forest root. |
| [`member`](ansible/roles/domain_member/README.md) | Joins the host to the domain. |
| `standalone` | No structural role, modules only. |

## Modules

Any number per host, from the `modules` list.

| Module | OS | Description |
| ------ | -- | ----------- |
| [`identity`](ansible/modules/identity/README.md) | windows | Domain users, groups and OUs. |
| [`logon`](ansible/modules/logon/README.md) | windows | Who may log on to a host, and how. |
| [`gmsa`](ansible/modules/gmsa/README.md) | windows | KDS root keys and gMSA accounts. |
| [`shares`](ansible/modules/shares/README.md) | windows | SMB shares of synthetic data with per-group ACLs. |
| [`sql_server`](ansible/modules/sql_server/README.md) | windows | SQL Server Express with a demo database. |
| [`adcs`](ansible/modules/adcs/README.md) | windows | Enterprise Root CA with toggleable ESC1/ESC4/ESC8/ESC11. |
| [`laps`](ansible/modules/laps/README.md) | windows | Windows LAPS, with optional over-permissive read delegation. |
| [`trust`](ansible/modules/trust/README.md) | windows | Forest and external trusts with their DNS forwarders. |
| [`vulns`](ansible/modules/vulns/README.md) | windows | Toggleable AD misconfigurations; all off by default. |
| [`defender`](ansible/modules/defender/README.md) | windows | Microsoft Defender on or off, with excluded directories. |
| [`edr_server`](ansible/modules/edr_server/README.md) | linux | Elastic Stack, Fleet and Windows detection rules. |
| [`edr_agent`](ansible/modules/edr_agent/README.md) | windows | Enrols the Elastic Agent. |
| [`vpn`](ansible/modules/vpn/README.md) | linux | OpenVPN access box, split-tunnel into the lab. |

A role or module declares its requirements in `lab_meta.yml`, which `run.sh`
checks (`os`, `min_instance_type`, `requires_role`, `requires_lab_role`,
`requires_lab`).

## Users and groups

The `dc` role creates `LabUser1`-`LabUser10` and the domain admin.
[`identity`](ansible/modules/identity/README.md) adds named users, groups and
OUs (each keyed by name), and [`logon`](ansible/modules/logon/README.md) decides
who may log on to a host. Omit `identity`'s vars for a default ten-group org
chart.

```yaml
- name: dc01
  role: dc
  domain: lab.local
  modules:
    - name: identity
      vars:
        identity_groups:
          Server-Admins: [alice]
        identity_users:
          alice:
            display: Alice Martin
            groups: [Domain Admins]

- name: srv-win01
  role: member
  domain: lab.local
  modules:
    - name: logon
      vars:
        logon_admins: [Server-Admins]
        logon_deny_network: [Domain Admins]
```

## Layout

- `ansible/roles/` structural roles applied by `role`
- `ansible/modules/` capabilities applied per host via the `modules` list
- `ansible/inventory.aws_ec2.yml` dynamic inventory, keyed on instance tags
- `terraform/` network, security, keys, compute, secrets, expiry
- `examples/` ready-made lab definitions

Because the inventory is dynamic, `ansible-playbook site.yml` re-runs against a
live lab, with `--limit mod_<module>` / `--tags modules` to scope it:

```
cd ansible && export LAB_NAME=ad-lab AWS_REGION=eu-west-3
ansible-playbook site.yml --tags modules --limit mod_shares
```

Add a module by creating `ansible/modules/<name>/tasks/main.yml` (optionally
`defaults/main.yml`, `lab_meta.yml`, `README.md`) and listing `<name>` on a
host. No change to Terraform or `site.yml` is needed.

## AWS content

Per lab: one VPC, one public subnet, one EC2 instance per host (encrypted gp3,
IMDSv2), and an expiry Lambda that once `expires_hours` passes **terminates** the
lab — or stops it with `expires_action: stop`, or nothing with
`expires_enabled: false`. Each `./run.sh` resets that clock to `expires_hours`
from now, so a lab you are actively re-running stays alive; `stop.sh`/`start.sh`
do not. Hosts are reached over the VPN by internal IP.

Credentials go to `lab_credentials.txt` (0600); only the ones a lab actually uses
are listed. No credential is placed in EC2 user-data.

Ansible prints `Found variable using reserved name: tags` on every run — harmless,
from the EC2 inventory exposing instance tags, and not suppressible.
