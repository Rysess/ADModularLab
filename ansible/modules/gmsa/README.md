# Module: `gmsa`

Creates KDS root keys and group Managed Service Accounts.

## Requirements

| Key | Value |
| --- | ----- |
| `os` | `windows` |
| `min_instance_type` | `t3.medium` |
| `requires_role` | `dc` |

## Variables

| Variable | Default | Meaning |
| -------- | ------- | ------- |
| `gmsa_count` | `4` | Number of accounts, named `<prefix>1..<prefix>N` |
| `gmsa_name_prefix` | `gmsa` | Account name prefix |
| `gmsa_dedicated_kds_key` | `true` | One root key per gMSA |
| `gmsa_principals` | `[Domain Computers]` | Principals allowed to retrieve the password |
| `gmsa_kerberos_encryption_types` | `[aes128, aes256]` | Encryption types |

```yaml
modules:
  - name: gmsa
    vars:
      gmsa_count: 6
```

## Creates

- `RSAT-AD-PowerShell`.
- One KDS root key per gMSA, backdated ten hours so it is usable immediately.
  Valid for a single-DC lab only.
- `gmsa_count` accounts with `dNSHostName` set to `<name>.<domain>`.

## KDS root key pairing

Active Directory selects a gMSA's root key at creation — the most recently
effective one — and records it in `msDS-ManagedPasswordId`. It cannot be chosen
by the caller and does not change afterwards.

With `gmsa_dedicated_kds_key: true` the module interleaves creation (key 1,
`gmsa1`, key 2, `gmsa2`, ...) to give each account its own key. Set it to
`false` to create all accounts against the current key.

The final task decodes the root key GUID from `msDS-ManagedPasswordId` (16
bytes at offset 24), writes it to the account description and prints the
mapping:

```
gmsa1        -> c597a4de-2156-1fd2-fca0-7c9a06e739c3  [ok]
gmsa2        -> 1ccadff6-0d58-bc8f-bbfa-4e8d75221493  [ok]
KDS root keys in domain: 6
```

`[ROOT KEY NOT IN DOMAIN]` marks an account whose key is absent from
`CN=Master Root Keys`.

## Scope

KDS root keys live in the forest's Configuration partition. `requires_role: dc`
keeps the module on forest roots, which are in different forests when a lab has
several, so the keys never collide. Microsoft advises against deleting root
keys once services depend on them.

## Footprint

No resources beyond the domain controller. Under a minute.
