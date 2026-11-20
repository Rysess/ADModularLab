[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Account,
    [Parameter(Mandatory)][string]$Password,
    [Parameter(Mandatory)][string]$Guid
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Import-Module ActiveDirectory
$Ansible.Changed = $false

# The AES-256 key Microsoft published in MS-GPPREF 2.2.1.1.4; IV is all zeroes.
$key = [byte[]](0x4e, 0x99, 0x06, 0xe8, 0xfc, 0xb6, 0x6c, 0xc9, 0xfa, 0xf4, 0x93, 0x10, 0x62, 0x0f, 0xfe, 0xe8,
                0xf4, 0x96, 0xe8, 0x06, 0xcc, 0x05, 0x79, 0x90, 0x20, 0x9b, 0x09, 0xa4, 0x33, 0xb6, 0x6c, 0x1b)
$aes = [System.Security.Cryptography.Aes]::Create()
$aes.Key = $key
$aes.IV = New-Object byte[] 16
$aes.Mode = 'CBC'
$aes.Padding = 'PKCS7'
$plain = [System.Text.Encoding]::Unicode.GetBytes($Password)
$cipher = $aes.CreateEncryptor().TransformFinalBlock($plain, 0, $plain.Length)
$cpassword = [Convert]::ToBase64String($cipher).TrimEnd('=')

$name = ($Account -split '\\')[-1]
$xml = @"
<?xml version="1.0" encoding="utf-8"?>
<Groups clsid="{3125E937-EB16-4b4c-9934-544FC6D24D26}"><User clsid="{DF5F1855-51E5-4d24-8B1A-D9BDE98BA1D1}" name="$name" image="2" changed="2024-03-11 09:12:44" uid="{$Guid}"><Properties action="U" newName="" fullName="" description="Deployment account for workstation builds" cpassword="$cpassword" changeLogon="0" noChange="1" neverExpires="1" acctDisabled="0" userName="$Account"/></User></Groups>
"@

# Netlogon's SysVol is the share root (...\SYSVOL\sysvol); policies live under
# its <dns domain> folder, which is what \\<domain>\SYSVOL\<domain>\Policies shows.
$sysvol = (Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Services\Netlogon\Parameters').SysVol
$policies = Join-Path $sysvol "$((Get-ADDomain).DNSRoot)\Policies"
if (-not (Test-Path -LiteralPath $policies)) { throw "no SYSVOL policies folder at $policies" }
# Earlier versions wrote to <share root>\domain by mistake; tidy that away.
$stray = Join-Path $sysvol 'domain'
if (Test-Path -LiteralPath (Join-Path $stray "Policies\{$Guid}")) {
    Remove-Item -LiteralPath (Join-Path $stray "Policies\{$Guid}") -Recurse -Force
    if (-not (Get-ChildItem -LiteralPath $stray -Recurse -File)) { Remove-Item -LiteralPath $stray -Recurse -Force }
}
$dir = Join-Path $policies "{$Guid}\Machine\Preferences\Groups"
$path = Join-Path $dir 'Groups.xml'
if ((Test-Path -LiteralPath $path) -and ([System.IO.File]::ReadAllText($path) -ceq $xml)) { return }
New-Item -ItemType Directory -Path $dir -Force | Out-Null
[System.IO.File]::WriteAllText($path, $xml, (New-Object System.Text.UTF8Encoding $false))
# A GPT.INI makes the folder look like the policy it pretends to be.
$gpt = Join-Path $policies "{$Guid}\GPT.INI"
if (-not (Test-Path -LiteralPath $gpt)) {
    [System.IO.File]::WriteAllText($gpt, "[General]`r`nVersion=3`r`n")
}
"planted $path"
$Ansible.Changed = $true
