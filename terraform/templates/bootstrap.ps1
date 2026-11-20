<powershell>
# First-boot bootstrap. User data only installs it: the script is written to
# disk and registered as a SYSTEM startup task, so it runs on every boot no
# matter how EC2Launch treats a user-data script that reboots the machine.
# No credentials here: user data is readable from IMDS by anything on the host.
$ErrorActionPreference = 'Stop'
$dir = 'C:\ProgramData\adlab'
$path = Join-Path $dir 'bootstrap.ps1'
New-Item -ItemType Directory -Path $dir -Force | Out-Null
$script = @'
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$name = '${hostname}'

try {
    # Rename during the boot EC2 is already doing, instead of an extra reboot
    # later from Ansible. A DC cannot be renamed once promoted, so this is the
    # cheapest moment. Domain members keep the name through the join.
    $cs = Get-CimInstance Win32_ComputerSystem
    if ($env:COMPUTERNAME -ne $name.ToUpper() -and -not $cs.PartOfDomain) {
        # The rename needs a reboot; WinRM stays closed until it has happened,
        # so Ansible never connects to a host that is about to restart.
        Rename-Computer -NewName $name -Force
        shutdown.exe /r /t 5 /c "adlab: apply computer name" | Out-Null
        exit 0
    }

    # Lab hosts are disposable: Windows Update and its maintenance tasks only
    # burn CPU credits and slow every install the modules do.
    foreach ($svc in 'wuauserv', 'UsoSvc', 'WaaSMedicSvc') {
        $s = Get-Service -Name $svc -ErrorAction SilentlyContinue
        if ($s) {
            Stop-Service -Name $svc -Force -ErrorAction SilentlyContinue
            Set-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Services\$svc" -Name Start -Value 4 -ErrorAction SilentlyContinue
        }
    }
    New-Item -Path 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU' -Force | Out-Null
    Set-ItemProperty -Path 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU' -Name NoAutoUpdate -Value 1
    Get-ScheduledTask -TaskPath '\Microsoft\Windows\UpdateOrchestrator\' -ErrorAction SilentlyContinue |
        Disable-ScheduledTask -ErrorAction SilentlyContinue | Out-Null
    # Server Manager would start at every interactive logon (session module).
    Get-ScheduledTask -TaskName ServerManager -ErrorAction SilentlyContinue |
        Disable-ScheduledTask -ErrorAction SilentlyContinue | Out-Null

    # WinRM over HTTP with NTLM message encryption: credentials and traffic are
    # never in clear on the wire, even though the listener is plain HTTP.
    Enable-PSRemoting -Force -SkipNetworkProfileCheck
    Set-Item WSMan:\localhost\Service\AllowUnencrypted -Value $false -Force
    Set-Item WSMan:\localhost\Service\Auth\Basic -Value $false -Force
    Set-Item WSMan:\localhost\Service\Auth\Negotiate -Value $true -Force
    Set-Item WSMan:\localhost\Shell\MaxMemoryPerShellMB -Value 2048 -Force
    Set-Item WSMan:\localhost\Plugin\Microsoft.PowerShell\Quotas\MaxMemoryPerShellMB -Value 2048 -Force

    if (-not (Get-NetFirewallRule -Name 'WinRM-HTTP' -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -Name 'WinRM-HTTP' -DisplayName 'WinRM HTTP' -Enabled True `
            -Direction Inbound -Protocol TCP -Action Allow -LocalPort 5985 | Out-Null
    }
    Set-Service -Name WinRM -StartupType Automatic
    Start-Service -Name WinRM
}
catch {
    Write-Error "bootstrap failed: $($_.Exception.Message)"
    exit 1
}

'@
Set-Content -Path $path -Value $script -Encoding UTF8
$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$path`""
$trigger = New-ScheduledTaskTrigger -AtStartup
Register-ScheduledTask -TaskName 'adlab-bootstrap' -Action $action -Trigger $trigger `
    -User 'SYSTEM' -RunLevel Highest -Force | Out-Null
& powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $path
</powershell>
<persist>false</persist>
