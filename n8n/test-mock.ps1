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

npx --yes n8n import:workflow --input="$wf" | Out-Null
npx --yes n8n execute --id=cardnewsMock001 2>&1 |
  Select-String -Pattern 'Execution was|Execution error|"message":' |
  Select-Object -First 10
