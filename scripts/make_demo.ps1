param(
    [string]$OutputDir = "demos/generated/real_project_demo"
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
if ([System.IO.Path]::IsPathRooted($OutputDir)) {
    $ResolvedOutput = $OutputDir
} else {
    $ResolvedOutput = Join-Path $RepoRoot $OutputDir
}

python (Join-Path $PSScriptRoot "make_demo.py") --output-dir $ResolvedOutput
