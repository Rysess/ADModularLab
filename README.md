# AD Modular Lab

Config-driven Active Directory lab on AWS. A single `lab.yml` declares the hosts
and the modules each one runs. Terraform builds the infrastructure and generates
the Ansible inventory; Ansible applies the modules. Access is provided through an
OpenVPN profile generated at deployment.

## Install

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

Destroy the lab with `./clean.sh`.

## Configuration

Each host is declared in `lab.yml` with an `os`, a `role` (`dc`, `member` or
`standalone`) and a list of `modules`.

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

Optional per-host fields: `instance_type`, `disk_gb`, `private_ip`,
`source_dest_check`, `expose_ports`.

## Modules

| Module | OS | Description |
| --- | --- | --- |
| `dc` | windows | Promotes the domain controller, creates users and a domain admin. |
| `domain_member` | windows | Joins the host to the domain. |
| `gmsa` | windows | Creates KDS root keys and gMSA accounts. |
| `shares` | windows | SMB shares of synthetic data with per-group ACLs and AD groups. |
| `sql_server` | windows | SQL Server Express with a demo database. |
| `edr_server` | linux | Elastic Stack, Fleet and Windows detection rules. |
| `edr_agent` | windows | Enrols the Elastic Agent. |
| `vpn` | linux | OpenVPN access box, split-tunnel into the lab. |

A module may declare requirements in `ansible/modules/<module>/lab_meta.yml`
(`os`, `min_instance_type`). `run.sh` validates `lab.yml` against these before
deploying; bypass with `./run.sh --force`.

## Layout

- `ansible/roles/` structural roles applied by `role` (`dc`, `domain_member`)
- `ansible/modules/` capabilities applied per host via the `modules` list

## Adding a module

1. Create `ansible/modules/<name>/tasks/main.yml`
2. Optionally add `ansible/modules/<name>/lab_meta.yml` (`os`, `min_instance_type`)
3. Add `<name>` to a host `modules` list in `lab.yml`

No change to Terraform or `site.yml` is required.

## AWS content

Per lab: one VPC, one public subnet, and one EC2 instance per host in `lab.yml`.
Windows hosts run Server 2022, Linux hosts run Ubuntu 22.04. Credentials and
host addresses are written to `lab_credentials.txt`. Hosts are reached over the
VPN using their internal IPs.
