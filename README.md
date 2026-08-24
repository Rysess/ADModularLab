# AD Modular Lab

Config-driven Active Directory lab on AWS. A single `lab.yml` declares the hosts
and the modules each one runs. Terraform builds the infrastructure, Ansible
discovers it through the EC2 dynamic inventory and applies the modules. Access is
provided through an OpenVPN profile generated at deployment.

> The lab exposes WinRM (5985), RDP and SSH to the deploying machine's public IP,
> and runs deliberately weak Active Directory configurations. Do not connect it to
> anything you care about.

## Install

| Tool | Version |
| ---- | ------- |
| Terraform | >= 1.6 |
| Python | >= 3.9 |
| AWS CLI | v2 |
| `jq` | any |

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

Destroy the lab with `./clean.sh`, or pause it with `./stop.sh` / `./start.sh`.

Ready-made definitions live in [`examples/`](examples/README.md), from a single
DC to two forests with a child domain:

```
LAB_FILE=examples/minimal.yml ./run.sh
```

The default `lab.yml` costs about **$0.20/hour** in `eu-west-3`. Each lab also
deploys a Lambda that stops it once `lab.expires_hours` has passed, so a
forgotten lab stops charging for compute on its own.

## Configuration

Each host is declared with an `os`, a `role`, the `domain` it belongs to, and a
list of `modules`.

```yaml
lab:
  name: adshares-lab
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

Every `dc`, `child_dc` and `member` names the domain it serves or joins. There
is no default: one domain or five, each host says which it is in. A `child_dc`
is a child of its domain minus the first label, so `child.lab.local` is a child
of `lab.local`. Adding a second forest is another `dc` with another `domain`.

Host names are NetBIOS names: 15 characters maximum, alphanumeric and `-`.

Optional per-host fields: `instance_type`, `disk_gb`, `private_ip`, `ami`,
`windows_version`, `source_dest_check`, `expose_ports`, `vars`.

Optional `lab` fields: `domain_admin_display`, `expires_hours`, `expires_action`
(`stop` or `terminate`), `expires_enabled`, `imdsv1_enabled`.

Optional `defaults` fields: `windows_instance_type`, `linux_instance_type`,
`windows_disk_gb`, `linux_disk_gb`, `windows_version` (`2016`/`2019`/`2022`/`2025`),
`ubuntu_release`.

A `modules` entry is either a bare name or a mapping carrying variables for that
module on that host. A `vars` block does the same for the host itself. Both are
written to `ansible/host_vars/<host>.yml`.

```yaml
modules:
  - shares
  - name: gmsa
    vars:
      gmsa_count: 6
```

`run.sh` validates the lab file before Terraform runs and reports what is wrong
rather than failing twenty minutes into a deployment; bypass with
`./run.sh --force`.

## Roles

Applied from the `role` field, one per host.

| Role | OS | Description |
| ---- | -- | ----------- |
| [`dc`](ansible/roles/dc/README.md) | windows | Promotes the domain controller, creates users and a domain admin. |
| [`child_dc`](ansible/roles/domain_child/README.md) | windows | Promotes a child domain beneath a forest root. |
| [`member`](ansible/roles/domain_member/README.md) | windows | Joins the host to the domain. |
| `standalone` | any | No structural role, modules only. |

## Modules

Applied from the `modules` list, any number per host.

| Module | OS | Description |
| ------ | -- | ----------- |
| [`gmsa`](ansible/modules/gmsa/README.md) | windows | KDS root keys and gMSA accounts. |
| [`shares`](ansible/modules/shares/README.md) | windows | SMB shares of synthetic data with per-group ACLs and AD groups. |
| [`sql_server`](ansible/modules/sql_server/README.md) | windows | SQL Server Express with a demo database. |
| [`adcs`](ansible/modules/adcs/README.md) | windows | Enterprise Root CA with toggleable ESC1/ESC4/ESC8/ESC11. |
| [`laps`](ansible/modules/laps/README.md) | windows | Windows LAPS, with optional over-permissive read delegation. |
| [`trust`](ansible/modules/trust/README.md) | windows | Forest and external trusts, with their DNS conditional forwarders. |
| [`vulns`](ansible/modules/vulns/README.md) | windows | Toggleable AD misconfigurations; all off by default. |
| [`defender`](ansible/modules/defender/README.md) | windows | Microsoft Defender on or off, with excluded directories. |
| [`edr_server`](ansible/modules/edr_server/README.md) | linux | Elastic Stack, Fleet and Windows detection rules. |
| [`edr_agent`](ansible/modules/edr_agent/README.md) | windows | Enrols the Elastic Agent. |
| [`vpn`](ansible/modules/vpn/README.md) | linux | OpenVPN access box, split-tunnel into the lab. |

A role or module may declare requirements in `lab_meta.yml`, which `run.sh`
checks: `os`, `min_instance_type`, `requires_role`, `requires_lab_role` and
`requires_lab`.

## Layout

- `ansible/roles/` structural roles applied by `role`
- `ansible/modules/` capabilities applied per host via the `modules` list
- `ansible/group_vars/` connection settings; Terraform writes secrets and lab
  addressing here, gitignored
- `ansible/host_vars/` per-host variables, generated by Terraform
- `ansible/inventory.aws_ec2.yml` dynamic inventory, keyed on instance tags
- `terraform/` network, security, keys, compute, secrets, expiry
- `examples/` ready-made lab definitions

Hosts are grouped by tag: `windows` / `linux`, `role_<role>`, `mod_<module>`.
Because the inventory is dynamic, `ansible-playbook site.yml` can be re-run against
a live lab without Terraform, and `--limit` / `--tags` work as expected:

```
cd ansible
export LAB_NAME=adshares-lab AWS_REGION=eu-west-3
ansible-playbook site.yml --tags modules --limit mod_shares
```

Tags are `always`, `prepare`, `dc`, `child_dc`, `member`, `base` and `modules`.

## Adding a module

1. Create `ansible/modules/<name>/tasks/main.yml`
2. Optionally add `defaults/main.yml`, `lab_meta.yml` and `README.md`
3. Add `<name>` to a host `modules` list

No change to Terraform or `site.yml` is required.

## Snapshots

`./snapshot.sh` creates an AMI per instance. Set `ami: <id>` on a host to rebuild
from one, which skips the ~40 minute promotion and join cycle. A snapshot is not
sysprepped, so EC2 publishes no password data for it: those hosts keep the local
Administrator password from the snapshot.

## AWS content

Per lab: one VPC, one public subnet, one EC2 instance per host with encrypted gp3
root volumes and IMDSv2 required, and the expiry Lambda with its schedule and
role. Hosts are reached over the VPN using their internal IPs; VPN clients keep
their own `10.8.0.0/24` source addresses so authentication events attribute
correctly.

Passwords are separated by purpose and written to `lab_credentials.txt` (0600):
local Administrator per Windows host, domain admin, DSRM, lab users, SQL,
Elastic, the Elastic monitor user, the child-domain promotion account and the
trust secret. No credential is placed in EC2 user-data.
