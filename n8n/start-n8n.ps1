# Launch n8n for the card-news workflow.
# Run from PowerShell:  powershell -ExecutionPolicy Bypass -File .\start-n8n.ps1

$root = Split-Path -Parent $MyInvocation.MyCommand.Path

# n8n 2.x disables the Execute Command node by default. This turns it back on.
# Malformed JSON here silently falls back to '[]', so keep the exact form.
$env:NODES_EXCLUDE = '[]'

# Let Code nodes write prompt/result files with require('fs').
$env:NODE_FUNCTION_ALLOW_BUILTIN = 'fs'

# File nodes are sandboxed to ~/.n8n-files by default; widen to our run dir.
$env:N8N_RESTRICT_FILE_ACCESS_TO = Join-Path $root 'runs'

# Claude calls are slow. Default is unlimited, but be explicit.
$env:EXECUTIONS_TIMEOUT = '1800'

# Run the copy already unpacked in the npx cache instead of going through npx.
# `npx n8n` re-resolves to the newest release and re-downloads ~1GB, stalling
# startup for minutes; pinning the version does NOT help, because npx keys its
# cache by the spec string, so "n8n@2.38.5" is a different slot from "n8n".
# An n8n left over from a previous run keeps the SQLite file locked, and the
# new instance then dies with "Database ping failed" -- which reads like DB
# corruption but is not. Refuse to start a second one.
$busy = Get-NetTCPConnection -LocalPort 5678 -State Listen -ErrorAction SilentlyContinue
if ($busy) {
  $owner = Get-Process -Id $busy[0].OwningProcess -ErrorAction SilentlyContinue
  Write-Host "포트 5678을 이미 쓰고 있습니다 (PID $($busy[0].OwningProcess) $($owner.ProcessName))."
  Write-Host "이미 켜져 있으면 http://localhost:5678 을 그냥 여세요."
  Write-Host "멈춘 것이면: taskkill /F /T /PID $($busy[0].OwningProcess)"
  exit 1
}

. (Join-Path $root 'scriptsind-n8n.ps1')
$bin = Find-N8nBin

Write-Host "runs dir : $($env:N8N_RESTRICT_FILE_ACCESS_TO)"
Write-Host "editor   : http://localhost:5678"

if ($bin) {
  Write-Host "version  : n8n $(Get-N8nVersion $bin)  (npx 캐시)"
  node $bin
}
else {
  # First run on a fresh machine: let npx fetch it once, then the branch above
  # takes over on every later start.
  Write-Host "npx 캐시에 완전한 n8n이 없습니다. 처음 한 번은 내려받습니다 (몇 분 걸립니다)."
  npx --yes n8n
}
