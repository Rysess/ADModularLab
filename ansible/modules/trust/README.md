# Module: `trust`

Domain and forest trusts between domains in the lab, with the DNS conditional
forwarders they depend on.

## Requirements

| Key | Value |
| --- | ----- |
| `os` | `windows` |
| `min_instance_type` | `t3.medium` |
| `requires_role` | `dc` |

Runs on a domain controller. `microsoft.ad.domain_trust` writes only the local
side, so the module has to run on both domains' controllers with the same
`trust_password`; Terraform generates one per lab and publishes it.

A parent-child trust needs none of this: promoting a `child_dc` host creates it.

## Usage

```yaml
modules:
  - name: trust
    vars:
      trust_partners:
        - name: partner.local
          type: forest
          direction: bidirectional
```

A partner that is part of this lab is resolved to its domain controller through
the inventory; `dns_server` only needs setting for a domain outside it.

## Variables

| Variable | Default | Meaning |
| -------- | ------- | ------- |
| `trust_partners` | `[]` | `{ name, type, direction }` per partner, plus optional `dns_server` |
| `trust_default_type` | `forest` | `forest` or `external` |
| `trust_default_direction` | `bidirectional` | `inbound`, `outbound` or `bidirectional` |
| `trust_partner_wait_timeout` | `1800` | Seconds to wait for the partner's LDAP |
| `trust_retries` / `trust_delay` | `5` / `30` | Retry budget for DNS and trust creation |

Consumed from Terraform: `trust_password`.

## Does

Per partner:

1. Adds or repoints a DNS conditional forwarder for the partner zone.
2. Waits for TCP/389 on the partner's DC.
3. Waits for `_ldap._tcp.dc._msdcs.<partner>` SRV records to resolve.
4. Creates the local side of the trust.

## Second forest

A second forest root is an ordinary `role: dc` host with `domain_name`
overridden in its host-level `vars`:

```yaml
- name: dc02
  os: windows
  role: dc
  private_ip: 10.0.1.20
  vars:
    domain_name: partner.local
```

Domain admin, DSRM and lab user credentials are shared across both forests.

## Footprint

No resources beyond the domain controllers. A couple of minutes once both
domains are up.
