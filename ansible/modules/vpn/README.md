# Module: `vpn`

OpenVPN access box with a split tunnel into the lab. Hosts are addressed by
their internal IPs.

## Requirements

| Key | Value |
| --- | ----- |
| `os` | `linux` |
| `min_instance_type` | `t3.nano` |

The host must also carry:

```yaml
source_dest_check: false
expose_ports:
  - { port: 1194, proto: udp }
```

`source_dest_check: false` is required because the instance forwards traffic
for the VPN client range; `run.sh` refuses to deploy without it. Terraform adds
the matching return route.

## Variables

| Variable | Default | Meaning |
| -------- | ------- | ------- |
| `vpn_port` / `vpn_proto` | `1194` / `udp` | Listener |
| `vpn_cipher` | `AES-256-GCM` | Data cipher |
| `vpn_clients` | `[client1]` | One certificate and profile per name |
| `vpn_client_name` | `client1` | Seeds the default single client |
| `vpn_easyrsa_dir` / `vpn_server_dir` | `/etc/openvpn/easy-rsa`, `/etc/openvpn/server` | Layout |
| `vpn_easyrsa_algo` / `vpn_easyrsa_curve` | `ec` / `prime256v1` | PKI algorithm |
| `vpn_ca_cn` | `lab-ovpn-ca` | CA common name |
| `vpn_service` | `openvpn-server@server` | systemd unit |
| `vpn_profile_dir` | `ansible/` | Directory the `<client>.ovpn` profiles are fetched to |

Consumed from Terraform: `vpc_network`, `vpc_netmask`, `vpn_client_cidr`,
`vpn_client_network`, `vpn_client_netmask`. From the inventory: `dc_private_ip`.

A standalone VPN host needs no `domain`; give it one to push a search domain and
to choose which controller it points clients at in a multi-domain lab.

## Creates

- An easy-rsa PKI, a server certificate and one client certificate per
  `vpn_clients` entry.
- `server.conf` pushing a route for the VPC and, when the lab has a domain
  controller, the DC as DNS with the lab's search domain.
- Two `FORWARD` accept rules, persisted with `netfilter-persistent`. No NAT:
  the AWS route table sends the client range to this instance, so lab hosts see
  the client's own `10.8.0.0/24` address.
- One `<client>.ovpn` per name, fetched to `ansible/`. The default lab produces
  `ansible/client1.ovpn`; `vpn_clients: [alice, bob]` produces `alice.ovpn` and
  `bob.ovpn`.

Profiles are re-rendered on every run, so they follow the instance's public IP
across `stop.sh` / `start.sh`. Each client name becomes a certificate common
name, so give one profile per person to revoke access individually.

## Footprint

`t3.nano`, 8 GB disk. Two to three minutes.
