# Example lab definitions

Deploy any of these with `LAB_FILE=`:

```
LAB_FILE=examples/minimal.yml ./run.sh
```

The same variable applies to `./stop.sh`, `./start.sh`, `./snapshot.sh` and
`./clean.sh`. Copy one to `lab.yml` to make it the default.

| File | Contents | Hosts | Cost |
| ---- | -------- | ----- | ---- |
| [`minimal.yml`](minimal.yml) | One domain controller | 1 | $0.07/hr |
| [`vpn-only.yml`](vpn-only.yml) | VPN box only, for checking access and credentials first | 1 | $0.01/hr |
| [`adcs.yml`](adcs.yml) | DC and a CA on a member server, all four ESC scenarios | 2 | $0.14/hr |
| [`trusts.yml`](trusts.yml) | Two forests, a child domain, a forest trust, members in two domains, LAPS | 5 | $0.31/hr |
| [`detection.yml`](detection.yml) | DC, member, SQL, Elastic stack, agents, weak AD, VPN | 4 | $0.31/hr |
| [`reference.yml`](reference.yml) | Every configuration key, annotated | 8 | $0.52/hr |

`reference.yml` is documentation that happens to deploy. Read it to see the
whole schema; do not run it because it is the biggest.

## Choosing

- Checking AWS credentials and the VPN path: `vpn-only.yml`.
- Learning the tooling against a domain: `minimal.yml`.
- Certificate services work: `adcs.yml`.
- Cross-domain and cross-forest work: `trusts.yml`.
- Detection engineering: `detection.yml`, the only one with telemetry.

## Cost

`eu-west-3` on-demand, compute plus gp3, at the time of writing. `./stop.sh`
halts compute and keeps EBS, leaving roughly $0.0001/GB/hr. Every resource is
tagged `ExpiresAt` from `lab.expires_hours` so a reaper can clean up forgotten
labs.

## Domains

Every `dc`, `child_dc` and `member` names its `domain`. A `child_dc` is a child
of that domain minus the first label, so `child.lab.local` sits under
`lab.local`. A second forest is another `dc` with another domain.

## Writing your own

Start from `minimal.yml` and add hosts. `reference.yml` lists every key with
its default. `./run.sh` validates the file before Terraform runs and reports
what is wrong rather than failing twenty minutes into a deployment:

```
srv1: joins 'nope.local', which no domain controller in the lab serves
ca01: role 'adcs' needs >= t3.medium, host is t3.small
vpn01: runs the vpn module, so it needs source_dest_check: false
```
