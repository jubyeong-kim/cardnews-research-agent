<#
  Locate an n8n already unpacked in the npx cache and return the path to its
  bin script, or $null.

  Why not just call `npx n8n`: npx re-resolves to the newest release and
  re-downloads ~1GB, which stalls startup for minutes. Pinning the version
  does not help either -- npx keys its cache by the spec string, so
  "n8n@2.38.5" is a different slot from "n8n".

  Both start-n8n.ps1 and reactivate.ps1 dot-source this, so the two cannot
  drift apart: reactivate.ps1 used bare `npx --yes n8n` for its import step
  and kicked off exactly the download start-n8n.ps1 was written to avoid.
#>

function Find-N8nBin {
  $cands = Get-ChildItem "$env:LOCALAPPDATA\npm-cache\_npx\*\node_modules\n8n\bin\n8n" -ErrorAction SilentlyContinue
  if (-not $cands) { return $null }

  # Newest first, but only accept an install that also has the editor UI.
  # A half-finished download leaves the bin in place without it, and n8n then
  # boots and answers "Cannot GET /" instead of serving the editor.
  foreach ($c in ($cands | Sort-Object LastWriteTime -Descending)) {
    $root = $c.Directory.Parent.Parent.FullName          # ...\node_modules
    $ui = Join-Path $root 'n8n-editor-ui\dist\index.html'
    if (Test-Path $ui) { return $c.FullName }
  }
  return $null
}

function Get-N8nVersion([string]$bin) {
  if (-not $bin) { return '(없음)' }
  $pkg = Join-Path (Split-Path -Parent (Split-Path -Parent $bin)) 'package.json'
  if (-not (Test-Path $pkg)) { return '(알 수 없음)' }
  return (Get-Content $pkg -Raw | ConvertFrom-Json).version
}
