[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$WorkspaceRoot,

    [string]$AuditLogPath = ".sentrygate/audit_events.jsonl",

    [string]$ServerName = "sentrygate"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Convert-ToTomlPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    return $Path.Replace('\', '/')
}

function Convert-ToTomlString {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Value
    )

    if ($Value -match "[`r`n]") {
        throw "TOML string values cannot contain newlines."
    }

    return $Value.Replace('\', '\\').Replace('"', '\"')
}

if ([string]::IsNullOrWhiteSpace($WorkspaceRoot)) {
    throw "WorkspaceRoot must not be empty."
}

if ([string]::IsNullOrWhiteSpace($AuditLogPath)) {
    throw "AuditLogPath must not be empty."
}

if ([string]::IsNullOrWhiteSpace($ServerName)) {
    throw "ServerName must not be empty."
}

if ($ServerName -notmatch '^[A-Za-z0-9_-]+$') {
    throw "ServerName may contain only letters, numbers, underscores, and hyphens."
}

$repoRoot = (Get-Location).ProviderPath
$backendPath = Join-Path $repoRoot "backend"
$pythonCommand = Join-Path $backendPath ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $pythonCommand -PathType Leaf)) {
    Write-Error 'backend .venv Python not found. Run `cd backend; uv sync` first.'
}

$workspaceItem = Get-Item -LiteralPath $WorkspaceRoot -ErrorAction Stop
if (-not $workspaceItem.PSIsContainer) {
    throw "WorkspaceRoot must be an existing directory: $WorkspaceRoot"
}

$resolvedWorkspaceRoot = $workspaceItem.FullName

if ([string]::IsNullOrWhiteSpace($env:USERPROFILE)) {
    throw "USERPROFILE is not set; cannot locate Codex config directory."
}

$codexDir = Join-Path $env:USERPROFILE ".codex"
$configPath = Join-Path $codexDir "config.toml"

New-Item -ItemType Directory -Path $codexDir -Force | Out-Null

if (Test-Path -LiteralPath $configPath -PathType Container) {
    throw "Codex config path is a directory: $configPath"
}

$configExists = Test-Path -LiteralPath $configPath -PathType Leaf
if ($configExists) {
    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $backupPath = Join-Path $codexDir "config.toml.$timestamp.bak"
    Copy-Item -LiteralPath $configPath -Destination $backupPath
}
else {
    New-Item -ItemType File -Path $configPath -Force | Out-Null
}

$content = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8
if ($null -eq $content) {
    $content = ""
}

$newline = "`n"
if ($content.Contains("`r`n")) {
    $newline = "`r`n"
}

$tomlPythonCommand = Convert-ToTomlString (Convert-ToTomlPath $pythonCommand)
$tomlWorkspaceRoot = Convert-ToTomlString (Convert-ToTomlPath $resolvedWorkspaceRoot)
$tomlAuditLogPath = Convert-ToTomlString (Convert-ToTomlPath $AuditLogPath)
$tomlBackendPath = Convert-ToTomlString (Convert-ToTomlPath $backendPath)

$blockLines = @(
    "[mcp_servers.$ServerName]",
    "command = `"$tomlPythonCommand`"",
    "args = [",
    "  `"-m`",",
    "  `"app.mcp.server`",",
    "  `"--workspace-root`",",
    "  `"$tomlWorkspaceRoot`",",
    "  `"--audit-log-path`",",
    "  `"$tomlAuditLogPath`"",
    "]",
    "cwd = `"$tomlBackendPath`"",
    "startup_timeout_sec = 10",
    "tool_timeout_sec = 60",
    "enabled = true"
)
$serverBlock = ($blockLines -join $newline) + $newline

$escapedServerName = [System.Text.RegularExpressions.Regex]::Escape($ServerName)
$pattern = "(?ms)^\s*\[mcp_servers\.$escapedServerName\]\s*\r?\n.*?(?=^\s*\[|\z)"
$regex = [regex]$pattern

if ($regex.IsMatch($content)) {
    $newContent = $regex.Replace(
        $content,
        [System.Text.RegularExpressions.MatchEvaluator] {
            param($match)
            return $serverBlock
        },
        1
    )
}
elseif ([string]::IsNullOrWhiteSpace($content)) {
    $newContent = $serverBlock
}
else {
    $newContent = $content.TrimEnd("`r", "`n") + $newline + $newline + $serverBlock
}

Set-Content -LiteralPath $configPath -Value $newContent -Encoding UTF8 -NoNewline

Write-Host "Codex config path: $configPath"
Write-Host "Backend path: $backendPath"
Write-Host "Workspace root: $resolvedWorkspaceRoot"
Write-Host "Audit log path: $AuditLogPath"
Write-Host 'Restart Codex Desktop, then test sentry_list_directory(".")'
