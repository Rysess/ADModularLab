# Module: `identity`

Declarative domain users, groups and OUs. Runs on the controller that serves the
domain, so a `child_dc` populates its own child domain the same way.

## Requirements

| Key | Value |
| --- | ----- |
| `os` | `windows` |
| `min_instance_type` | `t3.medium` (`t3.small` on Core) |
| `requires_role` | `dc` or `child_dc` |

Applied in its own play ahead of every other module, so modules on other hosts
(`logon`, `shares`) can name the principals it creates.

## Variables

Users and groups are maps keyed by sAMAccountName. The short form is a name and
a value; the long form is a name and a mapping. Both may appear in the same map.

**The key is the sAMAccountName — the login name.** In `bob: Bob Reyes`, `bob`
is the account (`bob@lab.local`) and `Bob Reyes` is only the display name.
Groups reference members by that key, `[bob]`, never by display name.

| Variable | Default | Meaning |
| -------- | ------- | ------- |
| `identity_groups` | 10-group org chart | `name: members`, or `name: {members, ...}` |
| `identity_users` | `{}` | `name: display`, or `name: {display, ...}` |
| `identity_ous` | `[]` | OU paths, only for OUs nothing else references |
| `identity_update_password` | `on_create` | `always` re-applies a changed password |

```yaml
- name: dc01
  role: dc
  domain: lab.local
  modules:
    - name: identity
      vars:
        identity_groups:
          Server-Admins: [alice]
          Helpdesk: [bob, Server-Admins]     # a member is a user or a group
          Domain Admins: [alice]             # built-ins work too, not recreated
          Tier0-Admins:
            ou: Tier0/Admins
            scope: universal
            description: Forest administrators
            members: [alice]
        identity_users:
          bob: Bob Reyes
          alice:
            display: Alice Martin
            ou: Tier0/Admins
          svc_sql:
            display: SQL Service
            password: Summer2025!
```

A group's value is its member list, or a mapping of `members`, `description`,
`scope` (`global`, `domainlocal`, `universal`), `category` (`security`,
`distribution`) and `ou`. A user's value is its display name, or a mapping of
`display`, `description`, `firstname`, `surname`, `email`, `password`,
`enabled` and `ou`. `firstname` and `surname` are set only when given, not
inferred from the display name; `password` defaults to the lab user password.

A member is resolved by sAMAccountName, so it is a user or group key here, a
LabUser, or a built-in like `Domain Admins`. Naming a display name (`Bob Reyes`)
instead of the key (`bob`) fails at runtime; preflight warns first.

Membership is set only through `identity_groups`, a group's `members` list — a
user has no `groups`. A built-in (`Domain Admins`, `Remote Desktop Users`) may
be a group key: it is populated, never recreated or rescoped, so its members are
added without touching the existing group.

Two users may not share a display name in the same container: the object is
identified by its sAMAccountName (the key), but its CN is the display name, and
CNs are unique per container. Give one a different display or `ou`. Renaming a
user's display across runs renames the object; renaming its `ou` moves it.

Naming a group AD already has, built-in or not, adds members to it rather than
replacing it, so `Domain Admins: [alice]` works.

An `ou` on a user or group creates its path, parents included, so
`identity_ous` is only for empty OUs nothing else mentions.

## Re-runs

Which edits to `lab.yml` take effect on a second run:

| Change | Converges |
| ------ | --------- |
| display name | yes — the object is renamed |
| `ou` | yes — the object is moved |
| `enabled` | yes |
| description, email, name attributes | yes |
| password | only with `identity_update_password: always` (default `on_create`) |
| removing a user, group, OU, or member | no — nothing is deleted |

The module adds and updates; it never removes. To drop a user or group, delete
it in AD yourself, or destroy and redeploy the lab.

## Creates

Each OU, then each group, then each user, then group membership. Splitting
membership out lets a group name a user the same run creates, and lets groups
nest.

The default `identity_groups` reference `LabUser1`-`LabUser10`, which the `dc`
role creates. Lower `dc_lab_user_count` and supply `identity_groups` yourself.

SPNs and other deliberate weaknesses belong to the `vulns` module.

## Footprint

Seconds. No reboot.
