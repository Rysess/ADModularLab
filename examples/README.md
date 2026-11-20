# Example labs

Templates for `./lab new <name> --from <example>`. Each one is copied to
`labs/<name>/lab.yml`, which you then edit and deploy:

```
./lab new mini --from minimal
./lab up mini
```

| Example | What it shows | Hosts | Cost |
| ------- | ------------- | ----- | ---- |
| [`starter`](starter.yml) | The default: generated org, file server with loot and bots, VPN | 3 | $0.13/hr |
| [`minimal`](minimal.yml) | One domain controller | 1 | $0.05/hr |
| [`vpn-only`](vpn-only.yml) | Just the VPN path, several client profiles | 1 | $0.01/hr |
| [`identity`](identity.yml) | `identity` and `logon`: users, groups, OUs, flags, policy, logon rights | 2 | $0.10/hr |
| [`services`](services.yml) | `shares` (relay target), `sql_server`, `gmsa`, `defender` | 3 | $0.11/hr |
| [`vulns`](vulns.yml) | Every `vulns` toggle | 2 | $0.10/hr |
| [`adcs`](adcs.yml) | All four ESC scenarios | 2 | $0.10/hr |
| [`trusts`](trusts.yml) | Two forests, a child domain, a forest trust, LAPS | 5 | $0.25/hr |
| [`detection`](detection.yml) | Weak AD, Elastic stack, agents, VPN | 4 | $0.30/hr |
| [`breach`](breach.yml) | Assumed breach with several paths to Domain Admin | 4 | $0.16/hr |

Costs are `eu-west-3` on-demand, compute plus gp3, at the time of writing.
`./lab stop` halts compute and keeps EBS. Each lab stops or terminates itself
when `lab.expires` passes.

## Choosing

- Checking AWS credentials and the VPN path: `vpn-only`.
- Learning the tooling against a domain: `minimal`.
- A realistic company to explore: `starter`.
- Users, groups and logon tiering: `identity`.
- Practising one class of AD attack: `vulns`, `adcs`.
- Cross-domain and cross-forest work: `trusts`.
- A full exercise end to end: `breach`.
- Detection engineering: `detection`, the only one with telemetry.

## Writing your own

Start from `minimal` and add hosts. `./lab validate <lab>` shows what the file
expands to, and reports problems before anything is deployed:

```
srv01: joins 'nope.local', which no controller serves. Known: ['lab.local']
ca01: role 'adcs' needs >= t3.medium, host is t3.small
ws01: module 'session': @admin needs identity to generate at least 1 admin account(s)
```
