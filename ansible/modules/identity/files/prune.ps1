[CmdletBinding()]
param(
    [AllowEmptyCollection()][string[]]$Users,
    [AllowEmptyCollection()][object[]]$Groups,
    [string]$Marker = 'adlab'
)
# Only objects carrying the identity marker (adminDescription) are touched:
# built-ins, LabUsers and anything created by hand are never deleted.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Import-Module ActiveDirectory
$Ansible.Changed = $false

$keepUsers = @{}
$Users | ForEach-Object { $keepUsers[$_.ToLower()] = $true }
$keepGroups = @{}
foreach ($g in $Groups) { $keepGroups[([string]$g.name).ToLower()] = $g }

foreach ($u in Get-ADUser -LDAPFilter "(adminDescription=$Marker)") {
    if (-not $keepUsers.ContainsKey($u.SamAccountName.ToLower())) {
        Remove-ADUser -Identity $u -Confirm:$false
        "removed user $($u.SamAccountName)"
        $Ansible.Changed = $true
    }
}

foreach ($grp in Get-ADGroup -LDAPFilter "(adminDescription=$Marker)" -Properties member) {
    $spec = $keepGroups[$grp.SamAccountName.ToLower()]
    if (-not $spec) {
        Remove-ADGroup -Identity $grp -Confirm:$false
        "removed group $($grp.SamAccountName)"
        $Ansible.Changed = $true
        continue
    }
    # Membership of a managed group is exactly what lab.yml declares.
    $want = @{}
    foreach ($m in @($spec.members)) {
        $o = Get-ADObject -LDAPFilter "(sAMAccountName=$m)"
        if (-not $o) { $o = Get-ADObject -LDAPFilter "(sAMAccountName=$m`$)" }
        if ($o) { $want[$o.DistinguishedName.ToLower()] = $true }
    }
    foreach ($dn in @($grp.member)) {
        if (-not $want.ContainsKey($dn.ToLower())) {
            Remove-ADGroupMember -Identity $grp -Members $dn -Confirm:$false
            "removed $dn from $($grp.SamAccountName)"
            $Ansible.Changed = $true
        }
    }
}
