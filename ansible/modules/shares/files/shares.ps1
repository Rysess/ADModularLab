[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Root,
    [Parameter(Mandatory)][string]$NetBios,
    [AllowEmptyCollection()][object[]]$Shares
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$Ansible.Changed = $false

$wellKnown = @{
    'everyone'            = 'Everyone'
    'authenticated users' = 'NT AUTHORITY\Authenticated Users'
    'administrators'      = 'BUILTIN\Administrators'
    'users'               = 'BUILTIN\Users'
    'system'              = 'NT AUTHORITY\SYSTEM'
}

function Resolve-Principal([string]$Name) {
    $account = if ($Name -match '\\') { $Name }
               elseif ($wellKnown.ContainsKey($Name.ToLower())) { $wellKnown[$Name.ToLower()] }
               else { "$NetBios\$Name" }
    try {
        $sid = ([System.Security.Principal.NTAccount]$account).Translate(
            [System.Security.Principal.SecurityIdentifier])
    } catch {
        throw "cannot resolve '$Name' (as $account): $($_.Exception.Message)"
    }
    [pscustomobject]@{ Account = $account; Sid = $sid }
}

$inherit = [System.Security.AccessControl.InheritanceFlags]'ContainerInherit, ObjectInherit'
$none = [System.Security.AccessControl.PropagationFlags]::None
$allow = [System.Security.AccessControl.AccessControlType]::Allow

foreach ($s in $Shares) {
    $dir = Join-Path $Root $s.dir
    if (-not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
        "created $dir"
        $Ansible.Changed = $true
    }

    # Desired grants, strongest right wins when a principal is listed twice.
    $rank = @{ Read = 1; Change = 2; Full = 3 }
    $want = [ordered]@{}
    $want['S-1-5-32-544'] = @{ P = Resolve-Principal 'Administrators'; R = 'Full' }
    $want['S-1-5-18'] = @{ P = Resolve-Principal 'SYSTEM'; R = 'Full' }
    foreach ($pair in @(@('read', 'Read'), @('write', 'Change'), @('full', 'Full'))) {
        foreach ($n in @($s.($pair[0]))) {
            if (-not $n) { continue }
            $p = Resolve-Principal $n
            $k = $p.Sid.Value
            if (-not $want.Contains($k) -or $rank[$pair[1]] -gt $rank[$want[$k].R]) {
                $want[$k] = @{ P = $p; R = $pair[1] }
            }
        }
    }

    # NTFS: explicit, inheritance off, exactly the desired ACEs.
    $ntfs = @{ Read = 'ReadAndExecute'; Change = 'Modify'; Full = 'FullControl' }
    $acl = Get-Acl -LiteralPath $dir
    # Compare as SID|rights|inheritance, rights numeric with Synchronize folded
    # in: Windows stores "Modify" as "Modify, Synchronize" once applied.
    $sync = [int][System.Security.AccessControl.FileSystemRights]::Synchronize
    $key = {
        param($r)
        $sid = $r.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value
        "$sid|$([int]$r.FileSystemRights -bor $sync)|$([int]$r.InheritanceFlags)|$($r.AccessControlType)"
    }
    $before = (@($acl.Access | Where-Object { -not $_.IsInherited }) | ForEach-Object { & $key $_ } |
        Sort-Object) -join ';'
    $target = New-Object System.Security.AccessControl.DirectorySecurity
    foreach ($k in $want.Keys) {
        $rights = [System.Security.AccessControl.FileSystemRights]$ntfs[$want[$k].R]
        $target.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule(
                    $want[$k].P.Sid, $rights, $inherit, $none, $allow)))
    }
    $after = (@($target.Access) | ForEach-Object { & $key $_ } | Sort-Object) -join ';'
    if ($before -ne $after -or -not $acl.AreAccessRulesProtected) {
        $acl.SetAccessRuleProtection($true, $false)
        foreach ($r in @($acl.Access | Where-Object { -not $_.IsInherited })) {
            [void]$acl.RemoveAccessRuleSpecific($r)
        }
        foreach ($r in $target.Access) { $acl.AddAccessRule($r) }
        Set-Acl -LiteralPath $dir -AclObject $acl
        "NTFS ACL set on $dir"
        $Ansible.Changed = $true
    }

    # SMB: same grants, same strengths.
    $share = Get-SmbShare -Name $s.name -ErrorAction SilentlyContinue
    if (-not $share) {
        $new = @{ Name = $s.name; Path = $dir; FullAccess = 'BUILTIN\Administrators' }
        if ($s.description) { $new.Description = $s.description }
        New-SmbShare @new | Out-Null
        "created share $($s.name)"
        $Ansible.Changed = $true
        $share = Get-SmbShare -Name $s.name
    } elseif ($share.Path -ne $dir) {
        throw "share $($s.name) already exists at $($share.Path), not $dir"
    }

    $current = @{}
    foreach ($a in Get-SmbShareAccess -Name $s.name) {
        try {
            $sid = ([System.Security.Principal.NTAccount]$a.AccountName).Translate(
                [System.Security.Principal.SecurityIdentifier]).Value
        } catch { $sid = $a.AccountName }
        $current[$sid] = @{ Name = $a.AccountName; R = [string]$a.AccessRight; T = [string]$a.AccessControlType }
    }
    foreach ($k in $want.Keys) {
        if ($k -eq 'S-1-5-18') { continue }   # SYSTEM needs no share ACE
        $c = $current[$k]
        if (-not $c -or $c.R -ne $want[$k].R -or $c.T -ne 'Allow') {
            Grant-SmbShareAccess -Name $s.name -AccountName $want[$k].P.Account `
                -AccessRight $want[$k].R -Force | Out-Null
            "share $($s.name): $($want[$k].P.Account) -> $($want[$k].R)"
            $Ansible.Changed = $true
        }
    }
    foreach ($k in @($current.Keys)) {
        if ($want.Contains($k)) { continue }
        Revoke-SmbShareAccess -Name $s.name -AccountName $current[$k].Name -Force | Out-Null
        "share $($s.name): revoked $($current[$k].Name)"
        $Ansible.Changed = $true
    }

    $mode = if ($s.abe) { 'AccessBased' } else { 'Unrestricted' }
    $desc = [string]$s.description
    if ([string]$share.FolderEnumerationMode -ne $mode -or [string]$share.Description -ne $desc) {
        Set-SmbShare -Name $s.name -FolderEnumerationMode $mode -Description $desc -Force
        "share $($s.name): enumeration=$mode"
        $Ansible.Changed = $true
    }
}
