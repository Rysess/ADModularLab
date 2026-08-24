# Module: `defender`

Microsoft Defender on or off, and the directories excluded from it.

## Requirements

| Key | Value |
| --- | ----- |
| `os` | `windows` |
| `min_instance_type` | `t3.small` |

For a host running `edr_agent`, exclude paths there instead: Elastic Defend
does its own monitoring and has its own exclusion list.

## Variables

| Variable | Default | Meaning |
| -------- | ------- | ------- |
| `defender_enabled` | `true` | `false` uninstalls the `Windows-Defender` feature |
| `defender_excluded_dirs` | `['C:\excluded']` | Created, and excluded when Defender is on |
| `defender_exclusion_extensions` | `[]` | Excluded file extensions |
| `defender_exclusion_processes` | `[]` | Excluded process names |

```yaml
modules:
  - name: defender
    vars:
      defender_enabled: false
      defender_excluded_dirs: ['C:\excluded', 'C:\staging']
```

## Notes

`defender_enabled: false` uninstalls the feature rather than calling
`Set-MpPreference -DisableRealtimeMonitoring`, which tamper protection reverts.
The change may require a reboot, which the module performs.

The excluded directories are created whether or not Defender is enabled, so a
lab has the same paths either way.

## Footprint

None beyond the host. Under a minute, plus a reboot if the feature changed.
