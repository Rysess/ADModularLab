[CmdletBinding()]
param(
    [AllowEmptyCollection()][object[]]$Users,
    # JSON {sam: password}, passed as a SecureString so it never reaches a log.
    [Parameter(Mandatory)][securestring]$Passwords,
    [Parameter(Mandatory)][string]$Domain,
    [ValidateSet('always', 'on_create')][string]$UpdatePassword = 'on_create',
    [string]$Marker = 'adlab'
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Import-Module ActiveDirectory
$Ansible.Changed = $false

$plain = [System.Net.NetworkCredential]::new('', $Passwords).Password
$pw = @{}
($plain | ConvertFrom-Json).PSObject.Properties | ForEach-Object { $pw[$_.Name] = $_.Value }
$defaultPath = (Get-ADDomain).UsersContainer
$dc = (Get-ADDomainController).HostName
$errors = [System.Collections.Generic.List[string]]::new()
$changed = [System.Collections.Generic.List[string]]::new()

function Get-Opt($u, [string]$key) {
    if ($u -is [System.Collections.IDictionary]) { if ($u.Contains($key)) { return $u[$key] } return $null }
    $p = $u.PSObject.Properties[$key]
    if ($p) { return $p.Value }
    return $null
}

function Test-Password([string]$sam, [string]$password) {
    $entry = New-Object System.DirectoryServices.DirectoryEntry("LDAP://$dc", "$Domain\$sam", $password)
    try { return $null -ne $entry.NativeObject } catch { return $false } finally { $entry.Dispose() }
}

# Attribute name -> lab.yml key. Only keys a user actually sets are managed.
$attrs = [ordered]@{
    displayName                = 'display'
    description                = 'description'
    givenName                  = 'firstname'
    sn                         = 'surname'
    mail                       = 'email'
    company                    = 'company'
    l                          = 'office'
    physicalDeliveryOfficeName = 'office'
    title                      = 'title'
    department                 = 'department'
    telephoneNumber            = 'phone'
}
$props = @($attrs.Keys) + @('servicePrincipalName', 'adminDescription', 'userPrincipalName',
                            'Enabled', 'PasswordNeverExpires', 'DistinguishedName')

foreach ($u in $Users) {
    $sam = [string](Get-Opt $u 'name')
    try {
        $display = [string](Get-Opt $u 'display')
        if (-not $display) { $display = $sam }
        $path = [string](Get-Opt $u 'path')
        if (-not $path) { $path = $defaultPath }
        $enabled = if ($null -ne (Get-Opt $u 'enabled')) { [bool](Get-Opt $u 'enabled') } else { $true }
        $spn = @(Get-Opt $u 'spn') | Where-Object { $_ }
        $upn = "$sam@$Domain"
        $want = @{}
        foreach ($a in $attrs.Keys) {
            $v = Get-Opt $u $attrs[$a]
            if ($a -eq 'displayName') { $v = $display }
            if ($null -ne $v -and "$v" -ne '') { $want[$a] = [string]$v }
        }
        $want['adminDescription'] = $Marker
        $want['userPrincipalName'] = $upn
        $password = $pw[$sam]

        $obj = Get-ADUser -LDAPFilter "(sAMAccountName=$sam)" -Properties $props
        if (-not $obj) {
            $new = @{
                Name                 = $display
                SamAccountName       = $sam
                Path                 = $path
                Enabled              = $enabled
                PasswordNeverExpires = $true
                AccountPassword      = (ConvertTo-SecureString $password -AsPlainText -Force)
                OtherAttributes      = $want
            }
            try {
                New-ADUser @new
            } catch {
                # A rejected password leaves a disabled account behind; a later
                # run would then never set the password. Undo the half-create.
                $half = Get-ADUser -LDAPFilter "(sAMAccountName=$sam)"
                if ($half) { Remove-ADUser -Identity $half -Confirm:$false }
                throw
            }
            if ($spn) { Set-ADUser -Identity $sam -ServicePrincipalNames @{ Add = $spn } }
            $changed.Add("created $sam")
            continue
        }

        $replace = @{}
        foreach ($k in $want.Keys) {
            if ([string]$obj.$k -cne $want[$k]) { $replace[$k] = $want[$k] }
        }
        if ($replace.Count) {
            Set-ADUser -Identity $obj -Replace $replace
            $changed.Add("updated $sam ($($replace.Keys -join ', '))")
        }
        if (-not $obj.PasswordNeverExpires) { Set-ADUser -Identity $obj -PasswordNeverExpires $true }
        if ($obj.Enabled -ne $enabled) {
            Set-ADUser -Identity $obj -Enabled $enabled
            $changed.Add("$sam enabled=$enabled")
        }
        $haveSpn = @($obj.servicePrincipalName | Sort-Object)
        if (($haveSpn -join '|') -ne (@($spn | Sort-Object) -join '|')) {
            if ($spn) { Set-ADUser -Identity $obj -ServicePrincipalNames @{ Replace = $spn } }
            else { Set-ADUser -Identity $obj -ServicePrincipalNames $null }
            $changed.Add("$sam SPNs set")
        }
        # The CN is the display name, and the parent is the OU: rename / move.
        $cn = ($obj.DistinguishedName -split '(?<!\\),', 2)[0] -replace '^CN=', '' -replace '\\(.)', '$1'
        if ($cn -cne $display) {
            Rename-ADObject -Identity $obj -NewName $display
            $obj = Get-ADUser -Identity $sam
            $changed.Add("renamed $sam to '$display'")
        }
        $parent = ($obj.DistinguishedName -split '(?<!\\),', 2)[1]
        if ($parent -ne $path) {
            Move-ADObject -Identity $obj -TargetPath $path
            $changed.Add("moved $sam to $path")
        }
        if ($UpdatePassword -eq 'always' -and $password -and -not (Test-Password $sam $password)) {
            Set-ADAccountPassword -Identity $sam -Reset -NewPassword (ConvertTo-SecureString $password -AsPlainText -Force)
            $changed.Add("reset the password of $sam")
        }
    } catch {
        $errors.Add("${sam}: $($_.Exception.Message)")
    }
}

if ($changed.Count) { $Ansible.Changed = $true }
$changed
if ($errors.Count) {
    $Ansible.Failed = $true
    $errors | ForEach-Object { "FAILED $_" }
}
