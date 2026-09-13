<#
  Claude CLI wrapper for the n8n Execute Command node.

  Why this exists: Execute Command runs through cmd.exe on Windows, where
  multi-line commands break and Korean text in quotes gets mangled. So the
  prompt travels as a FILE and only its path goes on the command line.
  That also keeps user-supplied topics out of the shell string entirely.

  Always exits 0 and always writes one JSON object to stdout, because a
  non-zero exit makes the Execute Command node discard stdout and raise
  stderr as the error instead.

  Usage:
    ask-claude.ps1 -PromptFile <path> [-SessionId <id>]

  stdout on success:
    {"sessionId":"...","body":<whatever JSON Claude produced>,"usage":{...}}
  usage 는 이 호출에서 쓴 것의 합계다 (JSON 수리가 돌았으면 그것까지 포함).
         on failure: {"status":"error","reason":"...","detail":"..."}

  The body is passed through verbatim -- PowerShell 5.1's JSON parser never
  touches it. Validation is delegated to `node`, which is the same parser n8n
  will use, so this script and n8n always agree on what counts as valid.

  Claude occasionally drops a brace in long nested output, so an invalid body
  gets ONE correction round in the same session before giving up. All three
  Claude calls in the workflow route through here, so this is the one place
  that needs to handle it.
#>
param(
  [Parameter(Mandatory = $true)][string]$PromptFile,
  [string]$SessionId = ''
)

# Keep Korean intact across the stdin pipe and the stdout capture.
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = New-Object System.Text.UTF8Encoding $false
$ErrorActionPreference = 'Continue'

$Utf8NoBom = New-Object System.Text.UTF8Encoding $false

# The validator lives in its own file: PowerShell strips embedded double
# quotes when passing an argument to a native command, so `node -e` is out.
$script:JsonCheck = Join-Path $PSScriptRoot 'json-check.js'

function Fail([string]$reason, [string]$detail = '') {
  $obj = [ordered]@{ status = 'error'; reason = $reason; detail = $detail }
  [Console]::Out.Write(($obj | ConvertTo-Json -Compress))
  exit 0
}

function Clip([string]$s, [int]$n = 400) {
  if ($null -eq $s) { return '' }
  if ($s.Length -le $n) { return $s }
  return $s.Substring(0, $n)
}

# Take the FIRST complete JSON object, matching braces while skipping over
# string literals. Slicing from the first '{' to the last '}' instead would
# swallow any prose or second block Claude appended after the JSON.
function Get-FirstJsonObject([string]$t) {
  if ([string]::IsNullOrEmpty($t)) { return $null }
  $start = $t.IndexOf('{')
  if ($start -lt 0) { return $null }
  $depth = 0; $inStr = $false; $esc = $false
  for ($i = $start; $i -lt $t.Length; $i++) {
    $ch = $t[$i]
    if ($esc) { $esc = $false; continue }
    if ($ch -eq '\') { if ($inStr) { $esc = $true }; continue }
    if ($ch -eq '"') { $inStr = -not $inStr; continue }
    if ($inStr) { continue }
    if ($ch -eq '{') { $depth++ }
    elseif ($ch -eq '}') {
      $depth--
      if ($depth -eq 0) { return $t.Substring($start, $i - $start + 1) }
    }
  }
  return $null
}

# Validate with node, not PowerShell: n8n parses this with JSON.parse, and
# only node's parser is guaranteed to agree with it. Returns $null when the
# text is valid, otherwise the parser's message -- which gets handed back to
# Claude, because repairing a named error beats regenerating from scratch.
#
# The verdict travels on stdout rather than the exit code so that a missing
# node is reported as a broken validator instead of masquerading as bad JSON.
function Get-JsonError([string]$s) {
  if ([string]::IsNullOrWhiteSpace($s)) { return 'empty output' }
  $tmp = [System.IO.Path]::GetTempFileName()
  try {
    [System.IO.File]::WriteAllText($tmp, $s, $Utf8NoBom)
    $res = [string](& node $script:JsonCheck $tmp)
    if ([string]::IsNullOrWhiteSpace($res)) {
      Fail 'node_validator_unavailable' 'node 를 실행할 수 없어 JSON 검증을 못 했습니다. PATH 확인 필요.'
    }
    if ($res.StartsWith('OK')) { return $null }
    return $res.Substring(4).Trim()
  }
  finally { Remove-Item $tmp -Force -ErrorAction SilentlyContinue }
}

# One Claude round trip. Returns @{ text; sid } or calls Fail.
function Invoke-Claude([string]$text, [string]$session) {
  # Without this, `claude -p` denies WebFetch/WebSearch by default and the
  # deep-research step can never open a source -- every card comes back with
  # "미확인" as its 근거. Grant only those two: no Bash, no file writes.
  $cliArgs = @('-p', '--output-format', 'json', '--allowedTools', 'WebFetch', 'WebSearch')
  if (-not [string]::IsNullOrWhiteSpace($session)) { $cliArgs += @('--resume', $session) }

  # Do NOT use 2>&1 here: on PS 5.1 it wraps native stderr in ErrorRecords and
  # poisons $? even when the exe succeeded.
  try { $raw = ($text | & claude @cliArgs | Out-String) }
  catch { Fail 'claude_launch_failed' $_.Exception.Message }

  if ([string]::IsNullOrWhiteSpace($raw)) { Fail 'claude_empty_output' "exit=$LASTEXITCODE" }

  # Parse before checking the exit code: claude still prints a well-formed
  # envelope on auth/API failures, and its "result" field holds the only
  # human-readable reason. Bailing on the exit code first would hide it.
  $envelope = $null
  try { $envelope = $raw | ConvertFrom-Json } catch { }
  if ($null -eq $envelope) {
    if ($LASTEXITCODE -ne 0) { Fail 'claude_nonzero_exit' ("exit=$LASTEXITCODE :: " + (Clip $raw)) }
    Fail 'claude_envelope_not_json' (Clip $raw)
  }
  # Some CLI versions emit an array of messages; the last one carries the result.
  if ($envelope -is [System.Array]) { $envelope = $envelope[-1] }

  if ($envelope.is_error -eq $true -or $LASTEXITCODE -ne 0) {
    Fail 'claude_error' ([string]$envelope.result)
  }
  $out = [string]$envelope.result
  if ([string]::IsNullOrWhiteSpace($out)) { Fail 'claude_no_result_field' (Clip $raw) }

  # 사용량과 비용은 봉투에 이미 들어 있다. 버리면 어느 단계가 비싼지 알 수
  # 없다. 없는 CLI 버전도 있으므로 없으면 0 이 된다.
  $u = $envelope.usage
  # 해시테이블이 아니라 PSCustomObject 로 담는다. PowerShell 5.1 의
  # Measure-Object 는 해시테이블의 키를 속성으로 보지 못한다.
  $script:Calls += [PSCustomObject]@{
    durationMs   = [int]($envelope.duration_ms)
    costUsd      = [double]($envelope.total_cost_usd)
    inputTokens  = [int]($u.input_tokens)
    outputTokens = [int]($u.output_tokens)
    cacheCreate  = [int]($u.cache_creation_input_tokens)
    cacheRead    = [int]($u.cache_read_input_tokens)
  }
  return @{ text = $out; sid = ([string]$envelope.session_id) }
}

# 수리 루프가 여러 번 부르므로 호출마다 쌓는다. 마지막 것만 쓰면 수리
# 비용이 통째로 안 보인다.
$script:Calls = @()

if (-not (Test-Path -LiteralPath $PromptFile)) { Fail 'prompt_file_missing' $PromptFile }
$prompt = Get-Content -LiteralPath $PromptFile -Raw -Encoding UTF8
if ([string]::IsNullOrWhiteSpace($prompt)) { Fail 'prompt_file_empty' $PromptFile }

$r = Invoke-Claude $prompt $SessionId
$body = Get-FirstJsonObject $r.text
$err = if ($null -eq $body) { 'JSON 객체를 찾지 못했습니다.' } else { Get-JsonError $body }

# Up to two repair rounds. Each one names the parser error and hands the
# broken text back, so Claude patches that spot instead of re-deriving the
# whole storyboard -- regenerating is the step that dropped the brace.
for ($attempt = 1; $attempt -le 2 -and $null -ne $err; $attempt++) {
  $broken = if ($body) { $body } else { $r.text }
  $repair = @(
    '직전 출력이 유효한 JSON이 아니다. JSON 파서 오류는 다음과 같다.',
    '',
    $err,
    '',
    '아래 텍스트를 고쳐서 유효한 JSON 하나만 출력하라.',
    '- 내용을 새로 만들지 말고 깨진 부분만 고친다.',
    '- 설명 문장, 코드펜스, 주석 없이 JSON 객체 하나만 출력한다.',
    '- 중괄호와 대괄호의 짝을 맞추고, 문자열 안 줄바꿈은 \n 으로 이스케이프한다.',
    '',
    '--- 고칠 텍스트 ---',
    $broken
  ) -join "`n"

  $r = Invoke-Claude $repair $r.sid
  $body = Get-FirstJsonObject $r.text
  $err = if ($null -eq $body) { 'JSON 객체를 찾지 못했습니다.' } else { Get-JsonError $body }
}

if ($null -ne $err) {
  # Keep the whole failing text next to the prompt; the 400-char clip in the
  # error payload is never enough to tell what actually went wrong.
  $dump = Join-Path (Split-Path -Parent $PromptFile) ('FAILED-' + (Get-Date -Format 'HHmmss') + '.txt')
  try { [System.IO.File]::WriteAllText($dump, $r.text, $Utf8NoBom) } catch { }
  Fail 'result_json_invalid_after_repair' ($err + ' :: 전체 출력은 ' + $dump)
}

# Strip anything that could break out of the string we are about to build.
$sid = $r.sid -replace '[^A-Za-z0-9_-]', ''

# 합계를 같이 내보낸다. calls 가 1보다 크면 JSON 수리가 돌았다는 뜻이고,
# 그 자체가 봐야 할 신호다.
$sum = @{
  calls        = $script:Calls.Count
  durationMs   = ($script:Calls | Measure-Object durationMs   -Sum).Sum
  costUsd      = ($script:Calls | Measure-Object costUsd      -Sum).Sum
  inputTokens  = ($script:Calls | Measure-Object inputTokens  -Sum).Sum
  outputTokens = ($script:Calls | Measure-Object outputTokens -Sum).Sum
  cacheCreate  = ($script:Calls | Measure-Object cacheCreate  -Sum).Sum
  cacheRead    = ($script:Calls | Measure-Object cacheRead    -Sum).Sum
}
$usageJson = $sum | ConvertTo-Json -Compress
[Console]::Out.Write('{"sessionId":"' + $sid + '","body":' + $body + ',"usage":' + $usageJson + '}')
exit 0
