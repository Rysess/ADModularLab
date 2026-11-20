[CmdletBinding()]
param(
    [AllowEmptyCollection()][object[]]$Files,
    [Parameter(Mandatory)][string]$Root,
    [AllowEmptyCollection()][string[]]$Dirs,
    [int]$Noise = 0
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$Ansible.Changed = $false
$utf8 = New-Object System.Text.UTF8Encoding $false

function Write-LabFile([string]$Path, [string]$Content, [bool]$Overwrite) {
    if (Test-Path -LiteralPath $Path) {
        if (-not $Overwrite) { return }
        if ([System.IO.File]::ReadAllText($Path) -ceq $Content) { return }
    }
    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    [System.IO.File]::WriteAllText($Path, $Content, $utf8)
    "wrote $Path"
    $script:Ansible.Changed = $true
}

foreach ($f in $Files) {
    Write-LabFile $f.path ([string]$f.content) ([bool]$f.overwrite)
}

# Filler documents: deterministic per share, created once, never rewritten.
$topics = 'Budget', 'Forecast', 'Meeting_Notes', 'Onboarding', 'Roadmap', 'Inventory',
          'Invoice', 'Contract', 'Policy', 'Report', 'Timesheet', 'Training', 'Survey',
          'Minutes', 'Presentation', 'Audit', 'Procedure', 'Checklist', 'Proposal'
$exts = '.docx', '.xlsx', '.pdf', '.pptx', '.txt', '.csv', '.msg'
$subs = '', '', 'Archive', '2024', '2025', 'Projects', 'Templates', 'Old'
foreach ($d in $Dirs) {
    if ($Noise -le 0) { break }
    $dir = Join-Path $Root $d
    $seed = 0
    foreach ($ch in (Split-Path -Leaf $dir).ToCharArray()) { $seed = ($seed * 31 + [int]$ch) % 2147483647 }
    $rng = New-Object System.Random $seed
    for ($i = 0; $i -lt $Noise; $i++) {
        $sub = $subs[$rng.Next($subs.Count)]
        $name = '{0}_{1}-Q{2}_v{3}{4}' -f $topics[$rng.Next($topics.Count)], (2023 + $rng.Next(3)),
            (1 + $rng.Next(4)), (1 + $rng.Next(5)), $exts[$rng.Next($exts.Count)]
        $path = if ($sub) { Join-Path (Join-Path $dir $sub) $name } else { Join-Path $dir $name }
        # Draw everything before the existence check: skipping a draw for an
        # existing file would shift every later name and grow the share each run.
        $words = 1 + $rng.Next(20)
        if (Test-Path -LiteralPath $path) { continue }
        $body = "Internal document - $name`r`nOwner: $(Split-Path -Leaf $dir)`r`n" +
                ('Lorem ipsum dolor sit amet, consectetur adipiscing elit. ' * $words)
        Write-LabFile $path $body $false
    }
}
