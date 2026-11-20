# Module: `shares`

A file server worth breaking into. It publishes department shares with real
NTFS and SMB permissions, plants files holding the **working** credentials of
lab accounts, and runs bots that behave like users: one runs a script from a
share, one connects to every server listed in a file. Together they give real
attack paths (loot hunting, writable-script hijacking, NTLM capture and relay,
GPP passwords) instead of fake secrets.

## Requirements

| Key | Value |
| --- | ----- |
| `os` | `windows` |
| `min_instance_type` | `t3.small` |
| `requires_role` | `member`, `dc` or `child_dc` |
| `requires_lab_role` | `dc` |

Works best with `identity`. Its default service accounts are what the default
loot and bots use. Without it, defaults naming missing accounts are skipped.

## Quick start

```yaml
srv01:
  modules:
    shares:                    # 6 shares, 3 loot files, 2 bots, filler documents
```

Every setting can be written without its `shares_` prefix.

## Shares

```yaml
    shares:
      shares:
        Public:   { read: [Domain Users], write: [Domain Users] }
        Finance:  Finance-Team                  # short form: just the reader(s)
        IT:       { read: [IT-Admins, Helpdesk], write: [Helpdesk] }
        HR:       { read: [HR], abe: true }     # access-based enumeration
        Backups$: { read: [Backup-Admins] }     # hidden share
```

| Key | Meaning |
| --- | ------- |
| `read` | ReadAndExecute (NTFS) and Read (SMB) |
| `write` | Modify (NTFS) and Change (SMB) |
| `full` | Full Control on both |
| `abe` | Access-based enumeration: users only see what they can read |
| `description` | Share comment |
| `path` | Directory under `C:\Shares` (default: the name without `$`) |

Each share directory has inheritance turned off and holds exactly these ACEs
plus Administrators and SYSTEM. Re-runs converge both ACLs to the definition,
revoking anything extra. A principal that AD lacks is created as an empty
global group on the domain controller, so a share can be declared for a team
before it has members.

Default shares: `Public` (everyone writes), `Finance`, `HR` (ABE), `IT`
(Helpdesk writes), `DevOps`, and the hidden `Backups$`.

## Loot: files with real credentials

```yaml
      loot:
        - { kind: script,   share: DevOps,   file: pipelines/release.ps1, user: svc_sql }
        - { kind: unattend, share: Backups$, file: images/unattend.xml,  user: svc_backup }
        - { kind: gpp,      user: svc_deploy }
        - { kind: note,     share: Finance,  file: Handover.txt, user: LabUser1 }
```

The password is the account's real one, looked up from `identity` (or the lab
defaults). Set `password` to override it.

| `kind` | Planted as |
| ------ | ---------- |
| `script` | PowerShell building a `PSCredential` |
| `batch` | `net use ... /user:DOMAIN\user password` |
| `config` | `web.config` connection string and impersonation identity |
| `env` | `.env` with an LDAP bind password |
| `unattend` | `unattend.xml` AutoLogon, base64 "obfuscated" as Windows does |
| `note` | A handover note |
| `gpp` | `Groups.xml` with a `cpassword` in **SYSVOL** (MS14-025), on the DC; no `share`/`file` |
| `file` | Your own `content` |

## Bots: simulated users

```yaml
      bots:
        - { kind: script, user: svc_backup,  share: IT,     file: scripts/maintenance.ps1, every: 5 }
        - { kind: browse, user: svc_monitor, share: Public, file: monitoring/servers.txt,  every: 2 }
```

Each bot is a scheduled task (`\LabBots\`) running as a domain account with a
stored password. That password also lands in LSA secrets, which is one more
thing to find on the host.

- **`script`** runs `\\host\<share>\<file>` with PowerShell every `every`
  minutes. Anyone who can write to that share gets code execution as `user`.
- **`browse`** reads `<file>` every `every` minutes and opens each UNC path or
  host name listed in it. Add `\\<your-ip>\x` and the bot authenticates to you
  over NTLM, which you can capture or relay.

The files a bot reads are written once and never overwritten, so changes you
make survive `./lab up`. The bot's account is granted read on its share
automatically.

With the defaults, LabUser7 (a foothold account, in `Helpdesk`) can write the
`IT` share. The script bot there runs as `svc_backup`, which `identity` puts in
Backup Operators. That chain ends on the domain controller.

## Other settings

| Setting | Default | Meaning |
| ------- | ------- | ------- |
| `smb_signing` | `default` | `disabled` turns SMB signing off (a relay target); `required` turns it on |
| `noise` | `12` | Filler documents per share, so loot has to be looked for |
| `decoys` | `true` | Fake keys, tokens and dumps (`ntds.dit`, `.env`, `id_rsa` ...) for scanners |
| `root` | `C:\Shares` | Filesystem root |

## What you'll find

`./lab up` writes every planted path (loot locations, who each bot runs as, who
can write its file) to `labs/<lab>/walkthrough.md`.

## Footprint

Under a minute: files are written in one batch, not one WinRM call per file.
There is no reboot.
