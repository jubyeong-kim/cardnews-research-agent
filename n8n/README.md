# 카드뉴스 워크플로 (n8n) — MVP

주제 하나를 넣으면 유튜브·웹에서 자료를 모아 오고, **후보를 직접 골라** 심층 조사와 스토리보드까지 만듭니다.
캐리어 플랫폼 SNS 운영을 염두에 둔 것이라 기본 주제는 "여행 기념품 추천"입니다.

이번 MVP 범위는 **조사 → 후보 선택 → 심층조사 → 스토리보드 승인 → 원고 저장**까지입니다.
이미지 생성과 PNG/ZIP 내보내기는 다음 단계입니다.

---

## 1. 처음 한 번만: API 키 두 개 발급

둘 다 무료이고 결제 카드 등록이 필요 없습니다.

### YouTube Data API v3 — 영상 후보

1. [console.cloud.google.com](https://console.cloud.google.com) 로그인
2. 상단 프로젝트 선택기 → **새 프로젝트** → 이름 아무거나 (예: `cardnews`) → 만들기
3. **API 및 서비스 → 라이브러리** → `YouTube Data API v3` 검색 → **사용**
4. **API 및 서비스 → 사용자 인증 정보** → **+ 사용자 인증 정보 만들기 → API 키**
5. `AIza...` 복사
6. *(권장)* 그 키의 연필 아이콘 → **API 제한사항** → `키 제한` → `YouTube Data API v3`만 체크 → 저장

`search.list`는 **하루 100회 전용 쿼터**를 씁니다. 카드뉴스 한 건에 1회이므로 하루 100건까지 여유입니다.

### Tavily — 블로그·웹 후보

1. [tavily.com](https://tavily.com) → Sign up (구글/깃허브 로그인 가능)
2. 대시보드에 보이는 `tvly-...` 복사

무료 **월 1,000 크레딧**, 이 워크플로는 한 건에 1크레딧입니다.

### 키가 맞는지 먼저 확인 (선택)

`여기에_키`만 바꿔서 터미널에서 실행합니다. `items` / `results` 배열이 오면 정상입니다.
`403`은 API를 아직 사용 설정하지 않은 것, `400 keyInvalid`는 키가 틀린 것입니다.

```bash
curl -s "https://www.googleapis.com/youtube/v3/search?part=snippet&type=video&maxResults=2&regionCode=KR&relevanceLanguage=ko&q=여행+기념품&key=여기에_키"
```

```bash
curl -s -X POST https://api.tavily.com/search -H "Authorization: Bearer 여기에_키" -H "Content-Type: application/json" -d "{\"query\":\"여행 기념품 추천\",\"language\":\"ko\",\"max_results\":2}"
```

두 키 모두 **n8n Credentials에만** 넣습니다. 워크플로 JSON에는 들어가지 않습니다.

## 2. Claude CLI 로그인 확인

원고를 쓰는 엔진은 이 PC에 설치된 Claude CLI입니다. 별도 API 키는 필요 없지만 로그인은 되어 있어야 합니다.

```bash
claude /login
```

확인:

```bash
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\ask-claude.ps1 -PromptFile .\runs\_check\prompt.txt
```

잘 되면 이렇게 나옵니다.

```
{"sessionId":"31c0b0f2-...","body":{"status":"result","ok":true,"note":"Claude CLI 연결됨"}}
```

`{"status":"error","reason":"claude_error","detail":"Failed to authenticate..."}` 가 나오면 로그인이 풀린 것입니다.

## 3. n8n 실행

```bash
powershell -ExecutionPolicy Bypass -File .\start-n8n.ps1
```

`http://localhost:5678` 이 열립니다. 처음 실행이면 n8n이 소유자 계정을 만들라고 합니다 (이메일·비밀번호, 로컬에만 저장).

**`start-n8n.ps1`로 켜야 합니다.** 그냥 `npx n8n`으로 켜면 필요한 환경변수가 빠져서 다음이 깨집니다.

| 환경변수 | 없으면 |
|---|---|
| `NODES_EXCLUDE='[]'` | n8n 2.x는 Execute Command 노드를 기본 차단 → `Unrecognized node type` |
| `NODE_FUNCTION_ALLOW_BUILTIN='fs'` | Code 노드가 프롬프트·결과 파일을 못 씀 |
| `N8N_RESTRICT_FILE_ACCESS_TO` | 파일 접근이 `~/.n8n-files`로 제한됨 |

## 4. 워크플로 가져오기

n8n 화면 우상단 **⋯ → Import from File** 로 `workflows/cardnews-mvp.json`을 엽니다.

그다음 Credentials를 연결합니다.

- `유튜브 검색` 노드 → Credential 종류 **Query Auth** → Name `key`, Value = YouTube API 키
- `웹 검색` 노드 → Credential 종류 **Header Auth** → Name `Authorization`, Value `Bearer tvly-...`
  ← `Bearer` 뒤에 **한 칸 띄우고** 키를 붙입니다. 이걸 빠뜨리면 401이 납니다.

좌측 메뉴 **Credentials → Add credential** 에서 미리 만들어두거나, 노드를 열어
**Credential to connect with → Create new** 로 즉석에서 만들어도 됩니다.

## 5. 사용하기

1. 폼 주소는 **`http://localhost:5678/form/cardnews-start-form`** 입니다.

   노드의 `path` 파라미터가 `cardnews`인데도 n8n은 **`webhookId`를 경로로 등록**합니다.
   추측하지 말고 DB에서 확인하세요 — 이게 늘 정답입니다.

   ```bash
   python -c "import sqlite3;print([r for r in sqlite3.connect('file:'+__import__('os').path.expanduser('~/.n8n/database.sqlite')+'?mode=ro',uri=True).execute('select webhookPath,method from webhook_entity')])"
   ```

2. 폼이 404면 워크플로가 활성화되지 않은 것입니다. **실측으로 확인된 방법은 이것뿐입니다** —
   n8n을 끄고 DB에서 `active`와 `activeVersionId`를 **둘 다** 채운 뒤 다시 켭니다.
   `active`만 세우면 조용히 무시되고, `import:workflow`는 두 값을 모두 되돌려 놓습니다.

   ```bash
   powershell -File .\reactivate.ps1
   ```

   > UI의 **Publish** 버튼으로도 될 것으로 보이지만 이 환경에서 성공을 확인하지 못했습니다
   > (`workflow_published_version` 테이블이 계속 비어 있었습니다). 위 방법은 확인됐습니다.
3. 주제·기간·용도를 넣고 제출 → 잠시 후 후보 목록이 뜹니다.
4. 후보를 1~3개 고릅니다. **고르기 전에는 제작이 시작되지 않습니다.**
5. 독자층이 갈리면 질문 화면이 나옵니다. 답하면 이어집니다.
6. 스토리보드를 확인하고 **승인** 또는 **수정 요청**(지시 함께 작성).
7. 승인하면 `runs/<실행번호>/`에 파일이 떨어집니다.

## 산출물

```
runs/<실행번호>/
├─ candidates-raw.json      모아온 후보 (중복 정리 후)
├─ selection.json           내가 고른 후보
├─ prompt-*.txt             Claude에 실제로 보낸 프롬프트 (그대로 재현 가능)
├─ storyboard.json          승인된 스토리보드
├─ script.md               카드별 원고 (역할·제목·본문·근거·그림 계획)
└─ sources.md              출처 목록과 카드별 근거
```

## 흐름 점검 (키 없이)

API 키를 넣기 전에 흐름만 확인하고 싶으면 모의 워크플로를 씁니다. 검색과 폼을 가짜로 바꿔 끝까지 돌려 봅니다.

```bash
powershell -ExecutionPolicy Bypass -File .\test-mock.ps1
```

`Execution was successful` 이 나오면 통과입니다. 이 모의본은 검사도 겸합니다.

- 후보 정리가 8건을 6건으로 줄이는지 (URL 중복 1건 + 제목 중복 1건)
- `utm_`·`si=` 파라미터가 제거되고 `youtu.be` 링크가 같은 영상으로 병합되는지
- 화면에 넘기는 폼 필드 JSON이 n8n의 허용 규칙을 지키는지
- 후보 id가 체크박스를 왕복해 되돌아오는지

Claude를 실제로 두 번 호출하므로 1~2분 걸리고 로그인이 필요합니다.

## 알아둘 것

- **한 번에 한 건**입니다. 실행마다 별도 디렉터리와 별도 Claude 세션을 쓰므로 프로젝트가 섞이지 않지만, 동시에 여러 건을 돌리면 각각 따로 진행됩니다.
- **폼 화면은 새로고침해도 유지됩니다.** 대기 중 실행은 DB에 저장되고, n8n을 껐다 켜도 `waiting` 상태로 복구됩니다 (`~/.n8n` 폴더 유지 조건).
- **탭을 닫으면** 그 실행은 계속 대기 상태로 남습니다. n8n의 Executions 목록에서 정리하세요.
- **스토리보드 수정은 전체 재생성**입니다. "3번 카드만" 같은 부분 수정과 버전 보관은 이번 범위가 아닙니다.
- **네이버 검색은 빠져 있습니다.** 이유는 `DECISIONS.md`에 적어뒀습니다.

문제가 생기면 n8n 좌측 **Executions**에서 실패한 노드를 열어 보세요. Claude 실패 이유는 그대로 노출됩니다.
