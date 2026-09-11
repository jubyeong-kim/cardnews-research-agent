<#
  Import a workflow (optional), activate it, restart n8n, and wait for the
  form URL to actually answer.

  Why this exists: doing these four steps by hand went wrong twice.
    - `n8n import:workflow` silently resets BOTH `active` and `activeVersionId`.
    - Setting `active=1` alone is ignored; n8n 2.x needs `activeVersionId` too.
    - The form path comes from the node's `webhookId`, not its `path` parameter.
    - n8n only registers webhooks at startup, so a restart is required.

  Usage:
    .\reactivate.ps1                        # activate + restart what is in the DB
    .\reactivate.ps1 -Import .\workflows\cardnews-mvp.json
#>
param(
  [string]$WorkflowId = 'cardnewsMvp0001',
  [string]$Import = '',
  # 콜드 부팅은 300초를 넘긴다 (2026-09-11 실측: 밤새 꺼져 있다 켜니
  # 5분이 지나서야 에디터가 떴다). 짧게 잡으면 정상 부팅을 실패로 보고한다.
  [int]$TimeoutSec = 600
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$db = Join-Path $env:USERPROFILE '.n8n\database.sqlite'
. (Join-Path $root 'scripts/find-n8n.ps1')

function Stop-N8n {
  $busy = Get-NetTCPConnection -LocalPort 5678 -State Listen -ErrorAction SilentlyContinue
  if ($busy) {
    Write-Host "n8n 정지 (PID $($busy[0].OwningProcess))"
    & taskkill /F /T /PID $busy[0].OwningProcess 2>&1 | Out-Null
    Start-Sleep -Seconds 4
  }
  Get-Process node -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
  Start-Sleep -Seconds 2
}

# --- 1. import (optional) -------------------------------------------------
if ($Import) {
  if (-not (Test-Path $Import)) { throw "가져올 파일이 없습니다: $Import" }
  Stop-N8n
  Write-Host "가져오는 중: $Import"
  # Never `npx n8n` here: it re-resolves to the newest release and starts a
  # ~1GB download, which is the stall start-n8n.ps1 exists to avoid.
  $bin = Find-N8nBin
  if (-not $bin) { throw 'npx 캐시에 n8n이 없습니다. 먼저 start-n8n.ps1 을 한 번 실행하세요.' }

  # Set the side ports on the CHILD only. Assigning $env: here would leak them
  # into the Start-Process below, and n8n would come up on 5778 instead of
  # 5678 -- looking exactly like a boot that never finished.
  & cmd /c "set NODES_EXCLUDE=[]&& set N8N_PORT=5778&& set N8N_RUNNERS_BROKER_PORT=5779&& node ""$bin"" import:workflow --input=""$Import""" |
    Select-String 'Successfully|Error'
}

# --- 2. activate ----------------------------------------------------------
Stop-N8n
$py = @'
import sqlite3, sys
db, wid = sys.argv[1], sys.argv[2]
c = sqlite3.connect(db, timeout=30)
cur = c.cursor()
# active alone is ignored by n8n 2.x; activeVersionId must point at a version.
cur.execute("update workflow_entity set active=1, activeVersionId=versionId where id=?", (wid,))
c.commit()
row = c.execute("select active, activeVersionId from workflow_entity where id=?", (wid,)).fetchone()
print('activated rows=%d active=%s activeVersionId=%s' % (cur.rowcount, row[0], row[1]))
paths = [r[0] for r in c.execute("select distinct webhookPath from webhook_entity")]
print('webhookPaths=%s' % (paths or '(재기동 후 등록됨)'))
c.close()
'@
$tmp = [System.IO.Path]::GetTempFileName() + '.py'
[System.IO.File]::WriteAllText($tmp, $py, (New-Object System.Text.UTF8Encoding $false))
& python $tmp $db $WorkflowId
Remove-Item $tmp -Force -ErrorAction SilentlyContinue

# --- 3. restart -----------------------------------------------------------
Write-Host 'n8n 기동...'
Start-Process powershell -ArgumentList @(
  '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $root 'start-n8n.ps1')
) -WindowStyle Minimized

# --- 4. wait for the form, and say so either way --------------------------
# The path is the node's webhookId. Read it back rather than assuming.
$path = 'cardnews-start-form'
$url = "http://localhost:5678/form/$path"
$deadline = (Get-Date).AddSeconds($TimeoutSec)
Write-Host "폼 대기: $url"

while ((Get-Date) -lt $deadline) {
  Start-Sleep -Seconds 5
  try {
    $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
    if ($r.StatusCode -eq 200) {
      Write-Host ''
      Write-Host "준비 완료 → $url" -ForegroundColor Green
      exit 0
    }
  }
  catch { Write-Host '.' -NoNewline }
}

Write-Host ''
Write-Host "시간 초과 ($TimeoutSec 초). 진단:" -ForegroundColor Yellow
Write-Host "  editor : $(try { (Invoke-WebRequest 'http://localhost:5678/' -UseBasicParsing -TimeoutSec 5).StatusCode } catch { '응답 없음' })"
Write-Host "  form   : 404 (webhook 미등록)"
Write-Host '  n8n 창의 로그에서 "Activated workflow" 줄이 있는지 확인하세요.'
exit 1
