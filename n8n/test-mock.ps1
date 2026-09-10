# Runs the mocked workflow end to end with no API keys.
# Searches and form pages are replaced by canned data; Claude is called for real,
# so this needs `claude /login` and takes a minute or two.
#
# Uses side ports so it can run while start-n8n.ps1 is up.

$root = Split-Path -Parent $MyInvocation.MyCommand.Path

$env:NODES_EXCLUDE = '[]'
$env:NODE_FUNCTION_ALLOW_BUILTIN = 'fs'
$env:N8N_RESTRICT_FILE_ACCESS_TO = Join-Path $root 'runs'
$env:N8N_PORT = '5778'
$env:N8N_RUNNERS_BROKER_PORT = '5779'

$wf = Join-Path $root 'workflows\cardnews-mock.json'

# Same reason as start-n8n.ps1: bare `npx n8n` re-resolves to the newest
# release and re-downloads ~1GB. Use the cache that is already unpacked.
. (Join-Path $root 'scripts/find-n8n.ps1')
$bin = Find-N8nBin
if (-not $bin) { throw 'npx 캐시에 n8n이 없습니다. 먼저 start-n8n.ps1 을 한 번 실행하세요.' }

& node $bin import:workflow --input="$wf" | Out-Null
& node $bin execute --id=cardnewsMock001 2>&1 |
  Select-String -Pattern '\[모의\]|Execution was|Execution error|"message":' |
  Select-Object -First 30
