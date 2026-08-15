<powershell>
# Runs on every boot (<persist>), so it must be idempotent. No credentials:
# user-data is readable from IMDS.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

try {
    Enable-PSRemoting -Force -SkipNetworkProfileCheck

    Set-Item WSMan:\localhost\Service\AllowUnencrypted -Value $true -Force
    Set-Item WSMan:\localhost\Service\Auth\Basic -Value $true -Force
    Set-Item WSMan:\localhost\Shell\MaxMemoryPerShellMB -Value 1024 -Force

    if (-not (Get-NetFirewallRule -Name 'WinRM-HTTP' -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -Name 'WinRM-HTTP' -DisplayName 'WinRM HTTP' -Enabled True `
            -Direction Inbound -Protocol TCP -Action Allow -LocalPort 5985 | Out-Null
    }

    Set-Service -Name WinRM -StartupType Automatic
    Start-Service -Name WinRM
}
catch {
    Write-Error "WinRM bootstrap failed: $($_.Exception.Message)"
    exit 1
}
</powershell>
<persist>true</persist>
