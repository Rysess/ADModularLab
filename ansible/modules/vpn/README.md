# Module: `vpn`

OpenVPN access box with a split tunnel into the lab. Hosts are addressed by
their internal IPs.

## Requirements

| Key | Value |
| --- | ----- |
| `os` | `linux` |
| `min_instance_type` | `t3.nano` |

The host must also carry:

The simplest way to get one is `lab.vpn: true` (or `{clients: [alice, bob]}`),
which adds a `vpn01` host. Any host running `vpn` gets UDP 1194 exposed and
`source_dest_check: false` automatically (the instance forwards traffic for the
VPN client range), and Terraform adds the return route and a fixed Elastic IP.

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
| `vpn_profile_dir` | `labs/<lab>/vpn` | Directory the `<client>.ovpn` profiles are fetched to |

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
  the client's own address in the lab's `172.16.<n>.0/24` range.
- One `<client>.ovpn` per name, fetched to `labs/<lab>/vpn/`. The default is
  `client1.ovpn`; `clients: [alice, bob]` produces `alice.ovpn` and `bob.ovpn`.

The endpoint is an Elastic IP, so profiles keep working across `./lab stop` /
`./lab start`. Each lab has its own route (`10.<n>.0.0/16`), so profiles of
several labs can be connected at once. Each client name becomes a certificate
common name, so give one profile per person to revoke access individually.

## Footprint

`t3.nano`, 8 GB disk. Two to three minutes.
