<#
  워크플로를 고쳐서 n8n 에 반영한다. credential 을 잃지 않는 유일한 경로다.

  workflows/cardnews-mvp.json 은 템플릿이라 credential 이 들어 있지 않다
  (일부러 그렇게 둔다 — 키가 저장소에 들어가면 안 된다). 그래서 이 파일을
  그대로 import 하면 UI 에서 연결해 둔 키가 전부 날아간다. 순서는:

    1. build_wf.py 로 템플릿을 새로 만든다
    2. DB 사본을 내보낸다 (credential 은 여기에만 있다)
    3. reapply.py 로 새 템플릿에 credential 을 이어 붙인다
    4. reactivate.ps1 로 가져오기 + 활성화 + 재기동 + 폼 확인

  중간 산출물 두 개는 credential 이 박혀 있어 .gitignore 로 막혀 있다.

  사용법:
    .\deploy.ps1              # 빌드부터 폼 확인까지
    .\deploy.ps1 -SkipBuild   # 이미 빌드해 둔 템플릿으로
#>
param(
  [string]$WorkflowId = 'cardnewsMvp0001',
  [switch]$SkipBuild
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $root 'scripts/find-n8n.ps1')

$bin = Find-N8nBin
if (-not $bin) { throw 'npx 캐시에 n8n이 없습니다. 먼저 start-n8n.ps1 을 한 번 실행하세요.' }

$export = Join-Path $root 'mvp-from-db.json'
$merged = Join-Path $root 'workflows/cardnews-mvp-with-creds.json'

# --- 1. 템플릿 빌드 --------------------------------------------------------
if (-not $SkipBuild) {
  Write-Host '템플릿 빌드...'
  & python (Join-Path $root 'tools/build_wf.py')
  if ($LASTEXITCODE -ne 0) { throw '빌드 실패 — Code 노드 문법 오류일 수 있습니다.' }
}

# --- 2. DB 사본 내보내기 ---------------------------------------------------
# 옆 포트로 띄운다. 기본 포트를 쓰면 실행 중인 n8n 과 부딪힌다.
Write-Host "DB 사본 내보내기: $WorkflowId"
if (Test-Path $export) { Remove-Item $export -Force }
& cmd /c "set NODES_EXCLUDE=[]&& set N8N_PORT=5778&& set N8N_RUNNERS_BROKER_PORT=5779&& node ""$bin"" export:workflow --id=$WorkflowId --output=""$export""" |
  Select-String 'Successfully|Error'

if (-not (Test-Path $export)) {
  throw "내보내기 실패. n8n 에 $WorkflowId 워크플로가 없으면 먼저 UI 에서 Import 하고 키를 연결하세요."
}

# --- 3. credential 이어붙이기 ----------------------------------------------
& python (Join-Path $root 'tools/reapply.py') $export $merged
if ($LASTEXITCODE -ne 0) { throw 'credential 이어붙이기 실패.' }

# --- 4. 가져오기 + 활성화 + 재기동 -----------------------------------------
& (Join-Path $root 'reactivate.ps1') -Import $merged -WorkflowId $WorkflowId
exit $LASTEXITCODE
