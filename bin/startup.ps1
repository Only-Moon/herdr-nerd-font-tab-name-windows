<# 
herdr startup hook: bring up the watcher/event hooks and exit.
#>

param(
    [string]$PluginRoot = $env:HERDR_PLUGIN_ROOT
)

if (-not $PluginRoot) {
    $PluginRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Definition)
}

$entrypoint = Join-Path $PluginRoot "bin\herdr-nerd-font-tab-name"

# On Windows, herdr startup hooks run the command directly (no shell).
# The plugin registers event-driven one-shot via herdr-plugin.toml.
# This script just ensures the CLI is executable and exits.
if (Test-Path ($entrypoint + ".exe")) {
    $entrypoint += ".exe"
}

# Verify the CLI works
try {
    & $entrypoint --version 2>$null | Out-Null
    Write-Host "[nerd-font-tab-name] startup: event hooks active"
    exit 0
}
catch {
    Write-Error "[nerd-font-tab-name] startup failed: $_"
    exit 1
}