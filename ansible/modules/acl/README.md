# Module: `acl`

Grants Active Directory rights between principals — the ACE-based attack paths
BloodHound reports (GenericAll, GenericWrite, WriteDacl, WriteOwner …).

## Requirements

| Key | Value |
| --- | ----- |
| `os` | `windows` |
| `min_instance_type` | `t3.medium` (`t3.small` on Core) |
| `requires_role` | `dc` |

Runs on the controller. Principals and targets must already exist — the `dc`
role's LabUsers, built-ins, or anything the `identity` module created (which runs
first).

## Variables

| Variable | Default | Meaning |
| -------- | ------- | ------- |
| `acl_grants` | `[]` | List of `{ principal, target, right, access }` |

```yaml
- name: dc01
  role: dc
  domain: lab.local
  modules:
    - name: identity
      vars:
        identity_groups:
          Helpdesk: [bob]
          Tier0-Admins: [alice]
    - name: acl
      vars:
        acl_grants:
          - { principal: Helpdesk, target: Tier0-Admins, right: GenericAll }
          - { principal: bob,      target: alice,        right: GenericWrite }
```

`principal` and `target` are sAMAccountNames (user, group, or computer; a
computer's trailing `$` is optional). `right` is one of `GenericAll`,
`GenericWrite`, `WriteDacl`, `WriteOwner`, `WriteProperty`, `Self`,
`ExtendedRight` (all extended rights, e.g. DCSync or ForceChangePassword).
`access` is `Allow` (default) or `Deny`.

## Creates

One allow (or deny) ACE per grant on the target object's DACL. Idempotent: a
grant that already matches an existing ACE is skipped. Nothing is removed —
dropping a grant from `lab.yml` leaves the ACE in place.

## Footprint

Seconds. No reboot.
