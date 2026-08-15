# AD Modular Lab

Config-driven Active Directory lab on AWS. A single `lab.yml` declares the hosts
and the modules each one runs. Terraform builds the infrastructure, Ansible
discovers it through the EC2 dynamic inventory and applies the modules. Access is
provided through an OpenVPN profile generated at deployment.


## Requirements


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

## Cost

The default `lab.yml` costs about **$0.20/hour** in `eu-west-3`, compute plus
gp3. Instances are tagged `ExpiresAt` (`lab.expires_hours`, default 168) so a
scheduled job can reap them. `./stop.sh` halts compute and keeps EBS, leaving
roughly $0.0001/GB/hr.

## Configuration

Each host is declared in `lab.yml` with an `os`, a `role` (`dc`, `member` or `standalone`) and a list of `modules`.

```yaml
hosts:
  - name: dc01
    os: windows
    role: dc
    instance_type: t3.large
    private_ip: 10.0.1.10
    modules:
      - gmsa

  - name: srv-win01
    os: windows
    role: member
    instance_type: t3.medium
    modules:
      - shares
```

Optional per-host fields: `instance_type`, `disk_gb`, `private_ip`, `ami`,
`source_dest_check`, `expose_ports`.

Optional `lab` fields: `domain_admin_display`, `expires_hours`, `imdsv1_enabled`
(defaults to IMDSv2-only; set true to leave IMDSv1 reachable for SSRF scenarios).

Optional `defaults` fields: `windows_instance_type`, `linux_instance_type`,
`windows_disk_gb`, `linux_disk_gb`, `windows_version` (`2016`/`2019`/`2022`/`2025`,
default `2022`), `ubuntu_release` (default `22.04`).

Host names are NetBIOS names: 15 characters maximum, alphanumeric and `-`.

### Host variables

A host may carry a `vars:` block, written to `ansible/host_vars/<host>.yml`
alongside its module variables and overriding them.

### Domains

With one domain, naming it is optional. With two or more, every domain-bearing
host must declare the `domain_name` it serves or joins, and `run.sh` refuses
otherwise:

```yaml
# a second forest root
- name: dc02
  role: dc
  vars:
    domain_name: partner.local

# a child of lab.local; serves child.lab.local
- name: dc-child
  role: child_dc

# joins the child domain rather than the lab's
- name: srv-child
  role: member
  vars:
    domain_name: child.lab.local
```

A `child_dc` host is a child of the domain it belongs to, and serves
`child.<parent>` unless `domain_child_domain` says otherwise.

Roles and modules resolve "the DC for my domain" through `dc_hosts_by_domain`,
which is keyed on domain rather than on inventory order, so nothing needs
pinning when a lab holds several. `run.sh` rejects a host whose domain no
controller in the lab serves.

Domain admin, DSRM and lab user credentials are shared across every domain in a
lab.

### Module variables

A `modules:` entry is either a bare name or a mapping carrying variables for
that module on that host:

```yaml
modules:
  - shares
  - name: gmsa
    vars:
      gmsa_count: 6
```

Terraform writes those into `ansible/host_vars/<host>.yml`, so they override the
module's `defaults/main.yml` for that host only. Each module's README lists what
it accepts.

### Alternative lab definitions

[`examples/`](examples/README.md) holds ready-made definitions; deploy one with
`LAB_FILE=`:

| File | Contents | Cost |
| ---- | -------- | ---- |
| `examples/minimal.yml` | One domain controller | $0.07/hr |
| `examples/vpn-only.yml` | VPN only, for checking access first | $0.01/hr |
| `examples/adcs.yml` | DC and a CA on a member server, all four ESC scenarios | $0.14/hr |
| `examples/trusts.yml` | Two forests, a child domain, a forest trust, LAPS | $0.31/hr |
| `examples/detection.yml` | DC, member, SQL, Elastic stack, agents, weak AD, VPN | $0.31/hr |
| `examples/reference.yml` | Every configuration key, annotated | $0.52/hr |

```
LAB_FILE=examples/vpn-only.yml ./run.sh
```

The same variable applies to `./stop.sh`, `./start.sh`, `./snapshot.sh` and
`./clean.sh`.

## Roles

Applied from the `role` field, one per host.

| Role         | OS      | Description                                                       |
| ------------ | ------- | ----------------------------------------------------------------- |
| [`dc`](ansible/roles/dc/README.md) | windows | Promotes the domain controller, creates users and a domain admin. |
| [`member`](ansible/roles/domain_member/README.md) | windows | Joins the host to the domain. |
| [`child_dc`](ansible/roles/domain_child/README.md) | windows | Promotes a child domain beneath the forest root. |
| `standalone` | any     | No structural role, modules only.                                 |

Tags are `always`, `prepare`, `dc`, `child_dc`, `member`, `base` (all of them)
and `modules`.

## Modules

Applied from the `modules` list, any number per host.

| Module          | OS      | Description                                                       |
| --------------- | ------- | ----------------------------------------------------------------- |
| [`gmsa`](ansible/modules/gmsa/README.md) | windows | Creates KDS root keys and gMSA accounts. |
| [`shares`](ansible/modules/shares/README.md) | windows | SMB shares of synthetic data with per-group ACLs and AD groups. |
| [`sql_server`](ansible/modules/sql_server/README.md) | windows | SQL Server Express with a demo database. |
| [`edr_server`](ansible/modules/edr_server/README.md) | linux | Elastic Stack, Fleet and Windows detection rules. |
| [`edr_agent`](ansible/modules/edr_agent/README.md) | windows | Enrols the Elastic Agent. |
| [`vpn`](ansible/modules/vpn/README.md) | linux | OpenVPN access box, split-tunnel into the lab. |
| [`vulns`](ansible/modules/vulns/README.md) | windows | Toggleable AD misconfigurations; all off by default. |
| [`adcs`](ansible/modules/adcs/README.md) | windows | Enterprise Root CA with toggleable ESC1/ESC4/ESC8/ESC11. |
| [`laps`](ansible/modules/laps/README.md) | windows | Windows LAPS, with optional over-permissive read delegation. |
| [`trust`](ansible/modules/trust/README.md) | windows | Forest and external trusts, with their DNS conditional forwarders. |

A role or module may declare requirements in `lab_meta.yml`:

| Key | Meaning |
| --- | ------- |
| `os` | `windows`, `linux` or `any` |
| `min_instance_type` | minimum size, compared on memory |
| `requires_role` | the host's own `role` must be this |
| `requires_lab_role` | some host in the lab must have this `role` |
| `requires_lab` | some host in the lab must run this module |

`run.sh` validates the lab file against these before deploying, along with host
name, address, port, AMI, disk and uniqueness rules; bypass with
`./run.sh --force`.

## Layout

- `ansible/roles/` structural roles applied by `role` (`dc`, `domain_member`)
- `ansible/modules/` capabilities applied per host via the `modules` list
- `ansible/group_vars/` connection settings; Terraform writes secrets to
  `group_vars/all/lab_secrets.yml` and lab addressing to
  `group_vars/all/lab_facts.yml` (both gitignored)
- `ansible/host_vars/` per-host module variables, generated by Terraform
- `ansible/inventory.aws_ec2.yml` dynamic inventory, keyed on instance tags
- `terraform/` network, security, keys, compute, secrets
- `examples/` alternative lab definitions, annotated

Hosts are grouped by tag: `windows` / `linux`, `role_<role>`, `mod_<module>`.
Because the inventory is dynamic, `ansible-playbook site.yml` can be re-run against
a live lab without Terraform, and `--limit` / `--tags` work as expected:

```
cd ansible
export LAB_NAME=adshares-lab AWS_REGION=eu-west-3
ansible-playbook site.yml --tags modules --limit mod_shares
```

## Adding a module

1. Create `ansible/modules/<name>/tasks/main.yml`
2. Optionally add `ansible/modules/<name>/defaults/main.yml`,
   `lab_meta.yml` and `README.md`
3. Add `<name>` to a host `modules` list in `lab.yml`

No change to Terraform or `site.yml` is required.

## Credentials

Passwords are separated by purpose and written to `lab_credentials.txt` (0600):
local Administrator (one per Windows host, generated by EC2 and decrypted with the
lab key pair), domain admin, DSRM, lab users, SQL, Elastic, and the Elastic
monitor user. No credential is placed in EC2 user-data.

## AWS content

Per lab: one VPC, one public subnet, and one EC2 instance per host in `lab.yml`,
with encrypted gp3 root volumes and IMDSv2 required by default. Windows hosts run
Server 2022 and Linux hosts Ubuntu 22.04 unless `defaults` says otherwise. Hosts
are reached over the VPN using their internal IPs; VPN clients keep their own
`10.8.0.0/24` source addresses so authentication events attribute correctly.
