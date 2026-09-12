# -*- coding: utf-8 -*-
"""Builds workflows/cardnews-mvp.json. Keeps the embedded JS readable."""
import json, io, os

ROOT = 'C:/Users/jb660/Desktop/project_2/n8n'
ASK  = ROOT + '/scripts/ask-claude.ps1'
RUNS = ROOT + '/runs'
OUT  = ROOT + '/workflows/cardnews-mvp.json'
# 후보 화면의 "다시 조사하기" 링크가 가리킬 곳. 폼 경로는 노드의 path 가
# 아니라 webhookId 다 (README 참조).
FORM_URL = 'http://localhost:5678/form/cardnews-start-form'

# 후보 선택 화면에만 붙이는 CSS. n8n 폼을 실제로 띄워 마크업을 확인하고 짰다:
#   <div class='inputs-wrapper'>
#     <div class="form-group html">   … 설명
#     <div>                           … label + div.multiselect (클래스 없음)
# sanitizeCustomCss 는 태그만 걷어내고 CSS 는 통과시킨다 (&gt; 는 > 로 되돌린다).
# 선택자가 빗나가도 조용히 무시될 뿐 폼은 그대로 뜬다.
PICK_CSS = (
    # 소스 구역 제목을 본문(12px)과 확실히 구분한다. div.html h2 는 20px.
    'div.html h2{font-weight:800;margin:26px 0 10px;padding-bottom:6px;'
    'border-bottom:3px solid #ff6d5a}'
    'div.html h2:first-child{margin-top:2px}'
    # 옵션 한 줄이 길어 줄바꿈이 생긴다.
    '.multiselect-option{padding-top:10px}'
    '.multiselect-option label{line-height:1.5;text-align:left}'
    # 넓은 화면에서만 두 칸. 좁으면 지금처럼 위아래로 쌓인다.
    # 폼 기본 폭이 448px 이라 데스크톱에서는 양옆이 비어 있었다.
    '@media (min-width:1000px){'
    ':root{--container-width:980px}'
    '.inputs-wrapper{display:grid;grid-template-columns:minmax(0,1fr) 400px;'
    'gap:28px;align-items:start}'
    # 오른쪽(체크박스)만 따라오게 한다. 목록이 길면 그 안에서 스크롤된다.
    '.inputs-wrapper>div:last-child{position:sticky;top:14px;'
    'max-height:calc(100vh - 36px);overflow-y:auto}'
    '}'
)


def cmd(session=False):
    s = ' -SessionId "{{ $json.sessionId }}"' if session else ''
    return ('=powershell -NoProfile -ExecutionPolicy Bypass -File "%s"'
            ' -PromptFile "{{ $json.promptFile }}"%s' % (ASK, s))


# ---------------------------------------------------------------- JS snippets

JS_PREP = r"""
const fs = require('fs');
const f = $input.first().json;

// fieldName is honoured from typeVersion 2.4 up; fall back to the label anyway.
const topic   = String(f.topic   ?? f['주제'] ?? '').trim();
const purpose = String(f.purpose ?? f['용도와 독자'] ?? '').trim();
const period  = String(f.period  ?? f['조사 기간'] ?? '');
if (!topic) throw new Error('주제가 비어 있습니다.');

const days = period.includes('30') ? 30 : 7;
const now = new Date();
const after = new Date(now.getTime() - days * 86400000);

// Forward slashes on purpose: this string lives inside JSON, where a backslash
// would become an escape sequence. Node accepts / on Windows.
const runDir = '__RUNS__/' + $execution.id;
fs.mkdirSync(runDir, { recursive: true });

return [{ json: {
  topic, purpose, days,
  projectId: $execution.id,
  runDir,
  publishedAfter: after.toISOString().split('.')[0] + 'Z',
  tavilyRange: days === 30 ? 'month' : 'week',
  researchedAt: now.toLocaleString('ko-KR', { timeZone: 'Asia/Seoul' }),
} }];
""".strip().replace('__RUNS__', RUNS)

JS_CANDIDATES = r"""
const fs = require('fs');
const prep = $('준비').first().json;

const stripTags = s => String(s ?? '').replace(/<[^>]*>/g, '');
// Unescape &amp; LAST, or "&amp;lt;" would decode twice.
const unescapeHtml = s => String(s ?? '')
  .replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"')
  .replace(/&#0?39;/g, "'").replace(/&apos;/g, "'").replace(/&nbsp;/g, ' ')
  .replace(/&amp;/g, '&');
const clean = s => unescapeHtml(stripTags(s)).replace(/\s+/g, ' ').trim();

// The Code node sandbox has no URL or URLSearchParams — both throw
// ReferenceError — so canonicalise by string. An earlier try/catch version
// swallowed that error and silently stopped deduplicating anything.
const canon = (u) => {
  const s = String(u ?? '').trim().split('#')[0];
  if (!s) return '';
  const yb = s.match(/^https?:\/\/(?:www\.)?youtu\.be\/([A-Za-z0-9_-]+)/i);
  if (yb) return 'https://www.youtube.com/watch?v=' + yb[1];
  const qi = s.indexOf('?');
  if (qi < 0) return s.replace(/\/+$/, '');
  const kept = s.slice(qi + 1).split('&')
    .filter(p => p && !/^(utm_[^=]*|si|feature|fbclid|igshid|gclid)=/i.test(p));
  return (kept.length ? s.slice(0, qi) + '?' + kept.join('&') : s.slice(0, qi)).replace(/\/+$/, '');
};

const hostOf = u => (String(u ?? '').match(/^https?:\/\/([^/?#]+)/i) || ['', ''])[1].replace(/^www\./i, '');

const raw = [];
const sourceErrors = [];
// Two tallies: what the API returned, and what survived the quality filters.
// With only the second one, "결과 0건" blamed an empty API response even when
// the API returned plenty and our own filters dropped every item — so the
// screen told the user to just re-run, which could never help.
const apiCounts = { '유튜브': 0, '웹': 0 };
const counts = { '유튜브': 0, '웹': 0 };

for (const it of $input.all()) {
  const j = it.json ?? {};
  if (j.error) {
    sourceErrors.push(clean(j.error.message ?? JSON.stringify(j.error)).slice(0, 200));
    continue;
  }
  if (Array.isArray(j.items)) {                    // YouTube search.list
    apiCounts['유튜브'] += j.items.length;
    for (const v of j.items) {
      const vid = v?.id?.videoId;
      if (!vid) continue;
      counts['유튜브']++;
      const sn = v.snippet ?? {};
      raw.push({
        source: '유튜브', channel: clean(sn.channelTitle), title: clean(sn.title),
        summary: clean(sn.description).slice(0, 300),
        publishedAt: sn.publishedAt ? String(sn.publishedAt).slice(0, 10) : null,
        url: 'https://www.youtube.com/watch?v=' + vid,
      });
    }
  } else if (Array.isArray(j.results)) {           // Tavily
    apiCounts['웹'] += j.results.length;
    for (const r of j.results) {
      if (!r?.url) continue;
      // Tavily mixes in stubs with a one-word title and no body ("기념품").
      // They would still eat a slot on the selection screen.
      if (clean(r.title).length < 6 || clean(r.content).length < 20) continue;
      // Instagram / TikTok / Facebook cannot be extracted by anything we have
      // (verified: Tavily /extract returns failed_results for them), so they
      // could never ground a card. Drop them instead of wasting a slot.
      if (/(^|\.)(instagram|tiktok|facebook|threads)\.com$/i.test(hostOf(r.url))) continue;
      counts['웹']++;
      raw.push({
        source: '웹', channel: hostOf(r.url), title: clean(r.title),
        summary: clean(r.content).slice(0, 300),
        publishedAt: r.published_date ? String(r.published_date).slice(0, 10) : null,
        url: r.url,
      });
    }
  }
}

// A source can answer 200 with an empty list, and it can also answer with
// items that our filters then remove. Those need different advice: re-running
// helps with the first and never helps with the second.
if (counts['유튜브'] === 0) {
  sourceErrors.push(apiCounts['유튜브'] > 0
    ? '유튜브 ' + apiCounts['유튜브'] + '건이 왔지만 쓸 수 있는 영상이 없습니다 (영상이 아닌 채널·재생목록 결과).'
    : '유튜브 결과 0건 — API 키, 또는 하루 100회 검색 쿼터를 확인하세요.');
}
if (counts['웹'] === 0) {
  sourceErrors.push(apiCounts['웹'] > 0
    ? '웹 ' + apiCounts['웹'] + '건이 왔지만 전부 걸러졌습니다 (제목 6자·본문 20자 미만이거나 인스타·틱톡). 다시 실행해도 같습니다 — 주제를 바꿔 보세요.'
    : '웹 결과 0건 — Tavily가 같은 질의에도 간헐적으로 빈 응답을 줍니다. 다시 실행하면 대개 나옵니다.');
}

// same link -> one candidate
const byUrl = new Map();
for (const c of raw) {
  const k = canon(c.url);
  if (k && !byUrl.has(k)) byUrl.set(k, { ...c, url: k });
}

// same story -> one candidate.
// ponytail: 제목 토큰 자카드 유사도. 오탐이 보이면 임베딩 비교로 교체
const toks = s => new Set(String(s).toLowerCase().replace(/[^\p{L}\p{N}]+/gu, ' ').split(' ').filter(w => w.length > 1));
const jac = (a, b) => {
  const inter = [...a].filter(x => b.has(x)).length;
  const uni = new Set([...a, ...b]).size;
  return uni ? inter / uni : 0;
};

// Group within a source only. Across sources the titles overlap heavily on
// the query words ("여행 기념품 추천"), so a blog post gets absorbed into a
// video's group and the whole web source disappears from the shortlist --
// a video and an article about the same thing are different material anyway.
const groups = [];
for (const c of byUrl.values()) {
  const t = toks(c.title);
  const hit = groups.find(g => g.item.source === c.source && jac(g.tokens, t) >= 0.6);
  if (hit) { hit.also.push(c.url); continue; }
  groups.push({ tokens: t, item: c, also: [] });
}

// Round-robin across sources before capping. Taking the first 12 outright
// would drop the web source entirely, because YouTube returns 25 hits and
// merges first -- which is exactly what happened on the first live run.
const bySrc = new Map();
for (const g of groups) {
  if (!bySrc.has(g.item.source)) bySrc.set(g.item.source, []);
  bySrc.get(g.item.source).push(g);
}
const queues = [...bySrc.values()];
const picked = [];
while (picked.length < 12 && queues.some(q => q.length)) {
  for (const q of queues) {
    if (!q.length) continue;
    picked.push(q.shift());
    if (picked.length >= 12) break;
  }
}

const candidates = picked.map((g, i) => ({ id: 'c' + (i + 1), ...g.item, duplicates: g.also.length }));

// 후보 화면에서 조회수로 순위를 매기려고 id 를 모아 둔다. videos.list 는
// 1 유닛이라(search.list 는 100) 부담이 없다. 여기서 뽑는 이유는 canon() 이
// youtu.be 를 watch?v= 로 이미 고쳐 놓은 뒤라서다.
const vidOf = u => (String(u ?? '').match(/[?&]v=([A-Za-z0-9_-]{6,})/) || [])[1] ?? null;
const candidateVideoIds = [...new Set(candidates.map(c => vidOf(c.url)).filter(Boolean))].join(',');

if (!candidates.length) {
  throw new Error('후보가 0개입니다. 검색 오류: ' + (sourceErrors.join(' / ')
    || '없음 — 검색은 됐으나 결과가 비었습니다. 주제를 바꾸거나 기간을 30일로 넓혀 보세요.'));
}

const prompt = [
  '너는 카드뉴스 조사 보조다. 아래는 "' + prep.topic + '" 주제로 최근 ' + prep.days + '일 안에서 모은 후보다.',
  prep.purpose ? '이 카드뉴스의 용도와 독자: ' + prep.purpose : '',
  '',
  '각 후보마다 세 가지를 붙여라.',
  '- fit: 0~100 정수. 이 주제와 독자에 얼마나 맞는지.',
  '- value: 왜 그 점수인지. 이 주제·독자와 어떻게 맞닿는지 한 줄.',
  '- uncertainty: 제목과 요약만으로는 확인되지 않는 점 (날짜 미확인, 광고·협찬 의심, 출처 불명 등)',
  '',
  'fit 기준:',
  '  80~100  주제 그대로이고 독자가 바로 쓸 수 있다',
  '  60~79   주제에 맞지만 범위가 넓거나 일부만 해당된다',
  '  40~59   곁가지다. 카드 한 장 정도 나올 것이다',
  '  0~39    주제에서 벗어났다',
  '',
  '규칙:',
  '- 후보에 없는 사실을 지어내지 마라. 제목과 요약에서 읽히는 것만 쓴다.',
  '- 웹 검색을 하지 마라. 이 단계는 주어진 목록만 평가한다.',
  '- 점수를 비슷하게 몰아주지 마라. 후보들 사이에 순서가 보이게 매겨라.',
  '- 조회수나 유행은 판단하지 마라. 그건 따로 붙인다. 너는 주제 부합만 본다.',
  '- 아래 JSON 하나만 출력하고 다른 문장은 쓰지 마라.',
  '',
  '{"status":"result","candidates":[{"id":"c1","fit":85,"value":"...","uncertainty":"..."}]}',
  '',
  '후보:',
  JSON.stringify(candidates.map(c => ({
    id: c.id, source: c.source, channel: c.channel, title: c.title,
    publishedAt: c.publishedAt ?? '미확인', summary: c.summary,
  })), null, 1),
].join('\n');

const promptFile = prep.runDir + '/prompt-1.txt';
fs.writeFileSync(promptFile, prompt, 'utf8');
fs.writeFileSync(prep.runDir + '/candidates-raw.json', JSON.stringify(candidates, null, 2), 'utf8');

return [{ json: { ...prep, candidates, candidateVideoIds, sourceErrors, promptFile } }];
""".strip()

JS_PICK_FORM = r"""
const prev = $('후보 정리').first().json;

// ask-claude.ps1 hands over {sessionId, body} on success and
// {status:'error', reason, detail} on failure.
// 조회수 노드가 뒤에 붙어 $json 을 덮었으므로 이름으로 가져온다.
let out;
const raw = $('Claude: 후보 평가').first().json.stdout;
try { out = JSON.parse(raw); }
catch (e) { throw new Error('래퍼 출력을 JSON으로 읽지 못했습니다: ' + String(raw).slice(0, 400)); }
if (out.status === 'error') {
  throw new Error('Claude 실패 (' + out.reason + '): ' + String(out.detail ?? '').slice(0, 300));
}
const res = out.body ?? {};
const notes = new Map((res.candidates ?? []).map(c => [c.id, c]));

// 유튜브 조회수. 이 단계 Claude 는 웹 검색을 안 하므로 "유행" 을 판단할 근거가
// 없다. 그래서 실제 숫자를 붙인다. 조회수 자체보다 하루 평균이 낫다 — 3년 된
// 영상의 누적 조회수와 지난주 영상의 조회수는 같은 뜻이 아니다.
const stats = new Map();
try {
  for (const it of ($json.items ?? [])) {
    const sec = (String(it.contentDetails?.duration ?? '').match(/^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$/) || null);
    stats.set(it.id, {
      views: Number(it.statistics?.viewCount ?? 0),
      seconds: sec ? (+(sec[1] || 0)) * 3600 + (+(sec[2] || 0)) * 60 + (+(sec[3] || 0)) : null,
    });
  }
} catch (e) { /* 조회수 노드가 실패했으면 점수만으로 간다 */ }

const vidOf = u => (String(u ?? '').match(/[?&]v=([A-Za-z0-9_-]{6,})/) || [])[1] ?? null;
const DAY = 86400000;

const candidates = prev.candidates.map(c => {
  const n = notes.get(c.id) ?? {};
  const st = stats.get(vidOf(c.url)) ?? {};
  const days = c.publishedAt
    ? Math.max(1, Math.round((Date.now() - new Date(c.publishedAt).getTime()) / DAY))
    : null;
  return {
    ...c,
    fit: Number.isFinite(+n.fit) ? Math.max(0, Math.min(100, Math.round(+n.fit))) : null,
    value: n.value ?? '',
    uncertainty: n.uncertainty ?? '',
    views: st.views ?? null,
    seconds: st.seconds ?? null,
    perDay: (st.views && days) ? Math.round(st.views / days) : null,
  };
});

// 주제 부합도가 1순위, 같으면 하루 평균 조회수가 2순위. 두 값을 하나로 섞지
// 않는다 — 섞으면 왜 이 순서인지 화면에서 설명할 수가 없다.
const byRank = (a, b) => (b.fit ?? -1) - (a.fit ?? -1) || (b.perDay ?? -1) - (a.perDay ?? -1);
const yt = candidates.filter(c => c.source === '유튜브').sort(byRank);
const web = candidates.filter(c => c.source !== '유튜브').sort(byRank);

// The html field is the one place n8n does NOT escape for us.
const he = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;')
  .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const cut = (s, n) => { s = String(s ?? ''); return s.length > n ? s.slice(0, n - 1) + '…' : s; };
const num = v => v == null ? '' : v >= 10000 ? (v / 10000).toFixed(1) + '만' : String(v);
const mmss = s => s == null ? '' : Math.floor(s / 60) + '분';

// 영상 분석 상한. 여기서 걸릴 영상을 고르기 전에 알려 준다.
const MAX_SEC = 20 * 60;

const row = (c, no) => {
  const meta = [
    he(c.source),
    c.channel ? he(c.channel) : '',
    he(c.publishedAt ?? '날짜 미확인'),
    c.views != null ? '조회 ' + num(c.views) + (c.perDay ? ' (하루 ' + num(c.perDay) + ')' : '') : '',
    c.seconds != null ? mmss(c.seconds) : '',
    c.duplicates ? '같은 소재 ' + c.duplicates + '건 묶임' : '',
  ].filter(Boolean).join(' · ');

  const warn = (c.seconds != null && c.seconds > MAX_SEC)
    ? '<br><b>※ ' + mmss(c.seconds) + ' 영상이라 Gemini 영상 분석에서 제외됩니다 (설명란만 사용)</b>'
    : '';

  // 번호가 설명과 선택 목록을 잇는 유일한 열쇠다. 둘이 같은 번호를 쓰므로
  // c1 같은 내부 id 를 사람에게 보일 이유가 없다.
  return '<p><b>' + no + ' · ' + (c.fit == null ? '점수 없음' : c.fit + '점') + ' — ' + he(c.title) + '</b>'
    + '<br>' + meta
    + '<br>' + he(c.summary)
    + (c.value ? '<br><b>고른 이유</b> ' + he(c.value) : '')
    + (c.uncertainty ? '<br><b>불확실</b> ' + he(c.uncertainty) : '')
    + warn
    + '<br><a href="' + he(c.url) + '" target="_blank" rel="noopener">원문 보기</a></p>';
};

// h2 는 20px, 본문은 12px. customCss 가 굵기와 밑줄을 더한다.
const section = (title, arr, from) => '<h2>' + title + ' ' + arr.length + '개</h2>'
  + (arr.length ? arr.map((c, i) => row(c, from + i)).join('') : '<p>없습니다.</p>');

const head = '<p><b>조사 기준</b> ' + he(prev.researchedAt) + ' · 최근 ' + prev.days + '일 · 후보 ' + candidates.length + '개</p>'
  + (prev.sourceErrors.length
      ? '<p><b>소스 상태</b> ' + prev.sourceErrors.map(e => he(e)).join('<br>') + '</p>'
      : '')
  // 점수가 무엇이고 무엇이 아닌지 화면에서 밝힌다. "유행 점수" 로 오해하면
  // 근거 없는 숫자를 믿게 된다.
  + '<p><b>점수는 주제 부합도입니다</b> — 제목과 요약만 보고 매긴 것이고, 유행 지표가 아닙니다.'
  + ' 조회수는 실제 숫자이며 같은 점수일 때 순서를 가릅니다.</p>'
  + '<p><a href="' + FORM_URL_PLACEHOLDER + '">← 주제를 바꿔 처음부터 다시 조사하기</a>'
  + ' (새 조사가 시작되고 이 화면은 그대로 남습니다)</p>';

// 화면 순서 = 선택 목록 순서 = 번호 순서. 셋이 같아야 눈으로 짝을 찾지 않는다.
const shown = [...yt, ...web];

const fields = [
  { fieldLabel: '조사 결과', fieldType: 'html',
    html: head + section('유튜브', yt, 1) + section('웹·블로그', web, yt.length + 1) },
  {
    fieldLabel: '카드뉴스로 만들 것 (1~3개)', fieldName: 'picks', fieldType: 'checkbox',
    // 왼쪽 설명을 안 봐도 고를 수 있게 판단 재료를 옵션에 다 넣는다:
    // 번호 · 소스 · 점수 · 조회수 · 길이 · 제목.
    fieldOptions: { values: shown.map((c, i) => ({ option:
      (i + 1) + ' · ' + (c.source === '유튜브' ? '[영상]' : '[웹]')
      + (c.fit == null ? '' : ' ' + c.fit + '점')
      + (c.views != null ? ' · 조회 ' + num(c.views) : '')
      + (c.seconds != null ? ' · ' + mmss(c.seconds) : '')
      + ' — ' + cut(c.title, 70) })) },
    requiredField: true, limitSelection: 'range', minSelections: 1, maxSelections: 3,
  },
];

// n8n resolves this expression through String.replace, where $ starts a
// replacement pattern. Double it so a $ in a title survives intact.
const formFields = JSON.stringify(fields).split('$').join('$$');

// 번호 -> 후보 id. 선택 정리가 이걸로 되찾는다.
const ordered = shown.map(c => c.id);

return [{ json: { ...prev, candidates, ordered, sessionId: out.sessionId, formFields } }];
""".strip().replace('FORM_URL_PLACEHOLDER', repr(FORM_URL))

JS_PICKED = r"""
const fs = require('fs');
const prev = $('후보 화면 만들기').first().json;

const picked = $json.picks ?? $json['카드뉴스로 만들 것 (1~3개)'] ?? [];
const arr = Array.isArray(picked) ? picked : [picked];
// 옵션 텍스트 맨 앞의 번호로 되찾는다. n8n 폼 옵션은 키가 option 하나뿐이고
// 별도 value 가 없어 텍스트에 열쇠를 심어야 하는데, 화면에도 쓰는 번호를 쓰면
// c1 같은 내부 id 를 사람에게 보이지 않아도 된다.
const ordered = prev.ordered ?? [];
const ids = arr
  .map(s => Number((String(s).match(/^(\d+)\s/) || [])[1]))
  .filter(n => Number.isFinite(n) && n >= 1 && n <= ordered.length)
  .map(n => ordered[n - 1]);
const chosen = prev.candidates.filter(c => ids.includes(c.id));
if (!chosen.length) throw new Error('선택한 후보를 찾지 못했습니다: ' + JSON.stringify(arr));

fs.writeFileSync(prev.runDir + '/selection.json', JSON.stringify(chosen, null, 2), 'utf8');

// Split the picks by how their text can actually be retrieved. Asking the
// model to open these pages does not work: Naver and Instagram refuse the
// fetch and YouTube renders its description with JS, so every card came back
// with 미확인. We hold both API keys, so fetch the text ourselves.
//
// Route by what the URL IS, not by which search found it: Tavily also returns
// YouTube links, and canon() rewrites youtu.be to watch?v=, so a candidate can
// carry source='웹' and still be a video. Deciding by source label sent those
// to both endpoints and then threw the fetched text away.
const videoIdOf = u =>
  (String(u ?? '').match(/(?:[?&]v=|youtu\.be\/)([A-Za-z0-9_-]{6,})/) || [])[1] ?? null;

// Resolve the id once here and carry it on the candidate, so 심층조사 지시
// matches on the same value instead of re-deriving it with its own copy of
// the regex — two copies would silently drift apart.
const withVid = chosen.map(c => ({ ...c, videoId: videoIdOf(c.url) }));

const videoIds = [...new Set(withVid.map(c => c.videoId).filter(Boolean))];
const webUrls = [...new Set(withVid.filter(c => !c.videoId).map(c => c.url))];

return [{ json: { ...prev, chosen: withVid, videoIds: videoIds.join(','), webUrls } }];
""".strip()

JS_VIDEO = r"""
// Gemini 가 고른 영상을 직접 본다.
//
// snippet.description 은 쇼츠와 상당수 브이로그에서 비어 있다. 영상이 아무리
// 좋아도 거기서 나온 품목은 전부 미확인으로 떨어졌다. 설명 대신 화면과 말을
// 읽게 하고, 품목이 나오는 시각까지 받아 온다.
//
// 무료 한도는 요청당 영상 1개다. 그래서 영상 하나에 아이템 하나를 내보내고
// HTTP 노드가 각각 한 번씩 호출하게 둔다.
const prev = $('선택 정리').first().json;

const meta = new Map();
try {
  for (const it of ($('유튜브 원문').first().json.items ?? [])) meta.set(it.id, it);
} catch (e) { /* 노드가 실패했으면 길이를 모른 채 진행한다 */ }

// PT1H2M3S -> 초
const durSec = s => {
  const m = String(s ?? '').match(/^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$/);
  return m ? (+(m[1] || 0)) * 3600 + (+(m[2] || 0)) * 60 + (+(m[3] || 0)) : null;
};

// 20분 초과는 건너뛴다. 유튜브 URL 은 구간을 잘라 보낼 수 없어서 통째로 가거나
// 안 가거나 둘 중 하나다.
//
// 왜 20분인가 (2026-09-10 AI Studio 실측 한도, 무료 등급):
//   RPM 5/분, TPM 250K/분(입력), RPD 20/일 — 모델마다 따로 잡힌다.
//   실측 소모는 약 100 토큰/초 (17분 영상이 입력 104,823 토큰이었다).
//   250K ÷ 100 = 2,500초 = 41.7분 → 이보다 긴 영상은 요청 하나로도 TPM 초과다.
//   20분이면 약 120K 라 두 편이 같은 분에 겹쳐도 240K 로 들어간다.
//
// 건너뛴 영상도 설명 전문은 그대로 쓰이므로 지금 동작으로 돌아갈 뿐이다.
const MAX_SEC = 20 * 60;

// RPD 20 을 3 으로 나누면 하루 6회 실행. 더 돌려야 하면 이 값을 줄이거나,
// MODEL 을 gemini-3.7-flash 로 바꾸면 그 모델의 20 회를 따로 쓴다.
const MAX_VIDEOS = 3;   // 후보 선택 상한과 같다
const MODEL = 'gemini-3.5-flash';

const targets = [];
const skipped = [];
for (const c of prev.chosen) {
  if (!c.videoId) continue;
  const sec = durSec((meta.get(c.videoId) ?? {}).contentDetails?.duration);
  if (sec !== null && sec > MAX_SEC) { skipped.push(c.title + ' (' + Math.round(sec / 60) + '분, 너무 김)'); continue; }
  if (targets.length >= MAX_VIDEOS) { skipped.push(c.title + ' (편당 상한 초과)'); continue; }
  targets.push({ cid: c.id, videoId: c.videoId, title: c.title });
}

const SCHEMA = {
  type: 'object',
  properties: {
    summary: { type: 'string' },
    items: {
      type: 'array',
      items: {
        type: 'object',
        properties: { name: { type: 'string' }, at: { type: 'string' }, note: { type: 'string' } },
        required: ['name', 'at', 'note'],
      },
    },
  },
  required: ['summary', 'items'],
};

const ASK = [
  '이 영상에서 소개하는 실물 기념품·선물 품목을 뽑아라.',
  '카드뉴스 주제: ' + prev.topic,
  '',
  '규칙:',
  '- 화면에 글자로 보이거나 말로 언급된 이름만 적는다. 정식 제품명을 추측해',
  '  괄호로 덧붙이지 마라. 확인되지 않은 제품 동일시는 지어내기와 같다.',
  '- name 은 영상에 나온 표기 그대로.',
  '- at 은 그 품목이 처음 나오는 시각을 mm:ss 로.',
  '- note 는 영상에서 실제로 한 말이나 화면에 적힌 내용 한 줄. 없으면 빈 문자열.',
  '- 사 가는 물건이 아닌 것(식당에서 먹은 음식, 교통, 숙소)은 빼라.',
  '- 품목이 없으면 items 를 빈 배열로 둔다. 억지로 채우지 마라.',
  '- summary 는 이 영상이 무엇을 다루는지 두 문장.',
  '- summary 를 포함해 모든 값은 한국어로 쓴다. 실측: 이 지시가 없으면 summary 가 영어로 온다.',
].join('\n');

// n8n 은 아이템을 못 받은 노드를 건너뛴다. 그러면 체인이 멈춘다.
// 텍스트만 있는 요청 한 번으로 대신한다 — 영상 없음, 한도 소모 없음.
// ponytail: 빈 호출 1건. 분기가 필요해지면 IF 노드로 교체
if (!targets.length) {
  return [{ json: { skip: true, cid: null, title: '', skipped, body: { model: MODEL, input: 'ok' } } }];
}

return targets.map(t => ({
  json: {
    skip: false, cid: t.cid, videoId: t.videoId, title: t.title, skipped,
    body: {
      model: MODEL,
      input: [
        { type: 'text', text: ASK },
        { type: 'video', uri: 'https://www.youtube.com/watch?v=' + t.videoId },
      ],
      response_format: { type: 'text', mime_type: 'application/json', schema: SCHEMA },
    },
  },
}));
""".strip()

JS_DEEP = r"""
const fs = require('fs');
const prev = $('선택 정리').first().json;
const chosen = prev.chosen;

const cut = (s, n) => { s = String(s ?? ''); return s.length > n ? s.slice(0, n) + ' …(이하 생략)' : s; };

// Full descriptions from videos.list (search.list truncates them).
const vids = new Map();
try {
  for (const it of ($('유튜브 원문').first().json.items ?? [])) {
    vids.set(it.id, {
      title: it.snippet?.title ?? '',
      description: it.snippet?.description ?? '',
      channel: it.snippet?.channelTitle ?? '',
      publishedAt: it.snippet?.publishedAt ?? '',
      views: it.statistics?.viewCount ?? null,
    });
  }
} catch (e) { /* node errored; handled as 미확인 below */ }

// Page text from Tavily /extract.
const pages = new Map();
let extractFailed = [];
try {
  const j = $('웹 원문').first().json;
  for (const r of (j.results ?? [])) pages.set(r.url, String(r.raw_content ?? ''));
  extractFailed = (j.failed_results ?? []).map(f => f.url ?? String(f));
} catch (e) { /* node errored; handled as 미확인 below */ }

// Gemini 가 읽어 온 영상 내용. 후보 id 로 찾는다. 영상 분석 대상이 영상마다
// 아이템 하나를 내보내고 제미나이 영상 분석이 순서대로 답하므로 인덱스가 맞는다.
// interactions 응답에서 모델이 쓴 텍스트만 뽑는다.
//
// 최상위가 배열이다. generateContent 는 객체 하나를 주지만 이쪽은 청크를 JSON
// 배열로 흘려 준다 (Transfer-Encoding: chunked). 키 없이 호출해 확인했고,
// 오류도 [{"error":{...}}] 로 왔다. 객체 하나로 오는 경우도 받아 둔다.
const pickText = raw => {
  let payload;
  try { payload = JSON.parse(raw); }
  catch (e) { return { err: '응답이 JSON 이 아님: ' + String(raw).slice(0, 200) }; }
  const objs = Array.isArray(payload) ? payload : [payload];
  const bad = objs.find(o => o && o.error);
  if (bad) return { err: String(bad.error.message ?? JSON.stringify(bad.error)).slice(0, 200) };
  // output_text 는 같은 내용의 SDK 쪽 이름이고 응답에 붙어 오는 경우가 있다.
  const withText = objs.filter(o => o && o.output_text);
  if (withText.length) return { txt: String(withText[withText.length - 1].output_text) };
  // steps[] 에는 사고·도구 단계도 섞여 있다. model_output 만 이어 붙인다.
  // 스트리밍이면 조각으로 나뉘어 오므로 마지막 하나만 쓰면 잘린다.
  const txt = objs
    .flatMap(o => (o && Array.isArray(o.steps)) ? o.steps : [])
    .filter(st => st && st.type === 'model_output')
    .flatMap(st => (st.content ?? []).filter(c => c && c.type === 'text').map(c => c.text))
    .join('');
  return txt.trim() ? { txt } : { err: '빈 응답' };
};

const watched = new Map();
const videoErrors = [];
let skippedVideos = [];
try {
  const asked = $('영상 분석 대상').all().map(i => i.json);
  skippedVideos = asked[0]?.skipped ?? [];
  const got = $('제미나이 영상 분석').all().map(i => i.json);
  asked.forEach((a, idx) => {
    if (a.skip || !a.cid) return;
    const got1 = pickText(String((got[idx] ?? {}).data ?? ''));
    if (got1.err) { videoErrors.push(a.title + ': ' + got1.err); return; }
    let parsed = null;
    try { parsed = JSON.parse(got1.txt); } catch (e) { /* 스키마를 안 지켰으면 원문 그대로 */ }
    watched.set(a.cid, parsed ?? { summary: got1.txt, items: [] });
  });
} catch (e) { videoErrors.push('영상 분석 노드 미실행: ' + String(e.message ?? e).slice(0, 120)); }

const blocks = [];
let verified = 0;
for (const c of chosen) {
  const vid = c.videoId;   // resolved once in 선택 정리
  let body = '';
  if (vid && vids.has(vid)) {
    const v = vids.get(vid);
    body = ['제목: ' + v.title,
            '채널: ' + v.channel,
            '게시일: ' + String(v.publishedAt).slice(0, 10),
            v.views ? '조회수: ' + v.views : '',
            '설명 전문:', v.description].filter(Boolean).join('\n');
  } else if (pages.has(c.url)) {
    body = pages.get(c.url);
  }
  // 길이 제한은 여기서 건다. 영상 분석을 붙인 뒤에 자르면 설명 전문이 긴
  // 영상에서 분석이 통째로 날아간다 — 제일 값진 재료가 제일 먼저 잘린다.
  body = cut(body, 8000);
  // 영상 분석을 같은 블록에 접어 넣는다. 그래야 source-text.txt 에도 들어간다 —
  // 원문 대조가 그 파일로 품목명을 확인하므로, 빼면 Gemini 가 화면에서 본 품목이
  // not_in_source 로 잘못 찍힌다.
  const w = watched.get(c.id);
  if (w) {
    const seen = ['영상 분석 (Gemini 가 영상을 직접 보고 정리한 것):'];
    if (w.summary) seen.push(String(w.summary));
    for (const it of (w.items ?? [])) {
      seen.push('- ' + it.name + ' [' + (it.at || '시각 미상') + ']' + (it.note ? ' — ' + it.note : ''));
    }
    body = [body, seen.join('\n')].filter(s => String(s).trim()).join('\n\n');
  }

  if (body.trim()) verified++;
  blocks.push([
    '### ' + c.id + ' ' + c.title,
    'URL: ' + c.url,
    body.trim() ? '원문 본문(실제로 가져온 것):' : '원문 본문: 가져오지 못했습니다. 이 후보는 미확인으로 다룬다.',
    body.trim() ? body : '',
  ].filter(Boolean).join('\n'));
}

fs.writeFileSync(prev.runDir + '/sources-fetched.json', JSON.stringify({
  verified, total: chosen.length, extractFailed,
  watched: [...watched.keys()], videoSkipped: skippedVideos, videoErrors,
  blocks: blocks.map(b => b.length),
}, null, 2), 'utf8');

// Keep the raw material on disk. 원문 대조 reads it back to check that every
// item Claude reports actually appears in what we fetched — the one check for
// invention that needs no external service and cannot false-positive.
fs.writeFileSync(prev.runDir + '/source-text.txt', blocks.join('\n\n'), 'utf8');

const prompt = [
  '너는 카드뉴스 편집자다. 아래 후보를 심층 조사하고 스토리보드를 만들어라.',
  '',
  '주제: ' + prev.topic,
  prev.purpose ? '용도와 독자: ' + prev.purpose : '',
  '조사 기준: ' + prev.researchedAt + ' 기준 최근 ' + prev.days + '일',
  '',
  '아래에 각 후보의 원문 본문을 실제로 가져와 붙였다 (' + verified + '/' + chosen.length + '건 확보).',
  '유튜브는 videos.list의 설명 전문, 웹은 Tavily로 추출한 페이지 본문이다.',
  watched.size ? '영상 ' + watched.size + '건에는 Gemini 가 영상을 직접 보고 정리한 "영상 분석"이 붙어 있다. 이것도 원문으로 취급한다.' : '',
  '',
  blocks.join('\n\n'),
  '',
  '절차:',
  '1. 위 본문에서 구체적인 품목명을 뽑는다. 본문에 글자 그대로 있는 것만 뽑고, 정식 제품명을',
  '   추측해 괄호로 덧붙이지 마라. 확인되지 않은 제품 동일시는 지어내기와 같다.',
  '2. 각 품목을 WebSearch로 교차 확인한다. 검색어에 반드시 주제어("' + prev.topic + '")를 함께 넣는다.',
  '   품목명만 단독으로 검색하지 마라 — 쇼핑몰 상품페이지만 나와 검증이 되지 않는다.',
  '3. 각 품목에 itemType 을 붙인다. "장소"(가게·노포·백화점·테마파크처럼 지도에 찍히는 것)',
  '   또는 "제품"(과자·화장품처럼 물건). 장소는 뒤에서 구글 지도로 실재를 따로 확인한다.',
  '4. 근거 등급을 아래 기준대로 엄격히 매긴다.',
  '   - official     : 관광국·지자체·발표기관·해당 브랜드 공식 사이트. 1곳이어도 단언해도 된다',
  '   - confirmed    : 서로 다른 개인 블로그·기사 2곳 이상이 이 주제 맥락에서 언급',
  '   - weak         : 그런 출처가 1곳',
  '   - retail_only  : 쇼핑몰 상품페이지만 나옴. 판매 사실만 확인된 것이며 추천 근거가 아니다',
  '   - unconfirmed  : 못 찾음',
  '5. 원문에 광고·협찬·제휴 표기가 있는지 확인한다. "광고", "협찬", "수수료를 제공받습니다",',
  '   "쇼핑 커넥트", "쿠팡 파트너스", "AD", "sponsored" 등이 보이면 그 후보에서 나온 품목은',
  '   반드시 제휴 콘텐츠 출처임을 밝히고 카드의 한계에도 적는다.',
  '6. 카드 본문에 단언으로 쓸 수 있는 것은 official, confirmed, weak 이다.',
  '   official 은 공식 출처이므로 그대로 단언해도 된다.',
  '   weak 은 "오사카관광국에 따르면" 처럼 어디서 나온 말인지 문장에 밝혀 쓴다.',
  '   retail_only 와 unconfirmed 는 카드의 주장 근거로 쓰지 마라.',
  '7. 본문에 없는 가격·순위·수치를 채워 넣지 않는다. 재료가 부족하면 카드 수를 줄인다.',
  '8. 본문을 못 가져온 후보는 근거를 "미확인"으로 적는다.',
  '9. 대상 독자나 편집 방향에 따라 결과가 크게 달라질 때만 되묻는다.',
  '',
  '되물어야 하면 (정말 갈릴 때만, 한 번):',
  '{"status":"need_input","question":"...","options":["...","..."],"why":"이 답에 따라 무엇이 달라지는지 한 줄"}',
  '',
  '만들 수 있으면:',
  '{"status":"result","storyboard":{"audience":"...","angle":"...","hooks":["...","..."],',
  '"items":[{"name":"본문에 있던 품목명 그대로","from":"c1","itemType":"장소|제품",',
  '"evidence":"official|confirmed|weak|retail_only|unconfirmed",',
  '"affiliate":true,"query_used":"실제로 쓴 검색어","sources":["url"]}],',
  '"cards":[{"no":1,"role":"표지","title":"...","body":"...",',
  '"source":"확인한 URL / 미확인 / 해당 없음",',
  '"image_plan":"구도·분위기·색과 글자 넣을 빈 공간. 최종 문구는 그리지 않는다"}]}}',
  '',
  '규칙:',
  '- 카드는 5~8장. 표지는 관심을 끌고, 본문 카드는 하나의 핵심만, 마지막 카드는 요약 또는 다음 행동.',
  '- 근거 없는 순위·수치·과장 금지. 확인하지 못한 숫자는 아예 쓰지 마라.',
  '- 후킹 문구는 확인된 사실 범위 안에서만 쓴다.',
  '- 영상 분석에서 가져온 내용은 source 에 URL 과 함께 시각(mm:ss)을 적어라.',
  '- source 는 셋 중 하나다. 확인한 URL / 재료를 못 가져와 확인 못 했으면 "미확인" /',
  '  표지나 마무리처럼 새로운 사실을 주장하지 않는 카드는 "해당 없음". 주장이 없는 카드를',
  '  "미확인"으로 적지 마라 — 검증 실패로 읽힌다.',
  '- JSON 하나만 출력하고 다른 문장은 쓰지 마라.',
].join('\n');

const promptFile = prev.runDir + '/prompt-2.txt';
fs.writeFileSync(promptFile, prompt, 'utf8');

return [{ json: { ...prev, chosen, promptFile } }];
""".strip()

JS_PARSE = r"""
let out;
try { out = JSON.parse($json.stdout); }
catch (e) { throw new Error('래퍼 출력을 JSON으로 읽지 못했습니다: ' + String($json.stdout).slice(0, 400)); }
if (out.status === 'error') {
  throw new Error('Claude 실패 (' + out.reason + '): ' + String(out.detail ?? '').slice(0, 300));
}

const res = out.body ?? {};
if (res.status !== 'need_input' && res.status !== 'result') {
  throw new Error('알 수 없는 status: ' + String(res.status) + ' / ' + JSON.stringify(res).slice(0, 300));
}

// Context comes from the first pass. runDir / sessionId / candidates do not
// change when the question or revision loop sends execution back through here.
const ctx = $('심층조사 지시').first().json;
return [{ json: { ...ctx, ...res, sessionId: out.sessionId || ctx.sessionId } }];
""".strip()

JS_ANSWER = r"""
const fs = require('fs');
const ctx = $('응답 파싱').first().json;

// Same cap as the revision loop: this also runs back into Claude: 심층조사.
// Claude is told to ask at most once, so a third question means it is stuck.
const MAX_QUESTIONS = 2;
if ($runIndex >= MAX_QUESTIONS) {
  throw new Error('질문이 ' + MAX_QUESTIONS + '회를 넘었습니다. 조사 재료가 부족해 '
    + '스토리보드를 못 만들고 있습니다. 후보를 더 고르거나 주제를 좁혀 다시 실행하세요.');
}

const free = String($json.answerFree ?? $json['직접 입력 (위 선택 대신)'] ?? '').trim();
const pick = String($json.answer ?? '').trim();
const answer = free || pick;
if (!answer) throw new Error('답변이 비어 있습니다.');

const prompt = [
  '앞서 네가 물은 질문: ' + String(ctx.question ?? ''),
  '사용자 답변: ' + answer,
  '',
  '이 답변을 반영해 이어서 진행하라. 앞서 정한 규칙과 JSON 규약을 그대로 지킨다.',
  '이제는 {"status":"result","storyboard":{...}} 하나만 출력하라.',
].join('\n');

const promptFile = ctx.runDir + '/prompt-answer-' + Date.now() + '.txt';
fs.writeFileSync(promptFile, prompt, 'utf8');
return [{ json: { ...ctx, promptFile } }];
""".strip()

# 판정 규칙만 떼어 둔다. 아래 빌드 시점 검사가 워크플로와 "정확히 같은 코드"
# 를 돌리게 하려는 것이다. 복사본을 두면 둘이 조용히 어긋난다.
JS_VERDICT = r"""
// 띄어쓰기와 문장부호를 지우고 비교한다. 출처마다 멜라노cc, 멜라노CC,
// 멜라노 CC 로 제각각 쓴다.
const norm = s => String(s ?? '').toLowerCase().replace(/[\s··・,.()（）\[\]{}"'`~!?\/\\|:;_+=-]+/g, '');
const tokensOf = s => String(s ?? '')
  .split(/[\s··・,.()（）\[\]{}"'`~!?\/\\|:;_+=-]+/)
  .map(norm).filter(t => t.length >= 2);

function verdictOf(name, sourceText) {
  const hay = norm(sourceText);
  const full = norm(name);
  // "VC100 마스크팩 (퀄리티퍼스트 …)" — 괄호 앞이 주장이고, 괄호 안은 모델이
  // 정식 제품명을 추측해 붙인 것인 경우가 많다.
  const headRaw = String(name ?? '').split(/[(（]/)[0];
  const head = norm(headRaw);

  if (!full) return 'empty';
  if (!hay) return 'no_source';
  if (hay.includes(full)) return 'in_source';
  if (head && head !== full && hay.includes(head)) return 'head_only';

  // 통짜로는 없지만 단어가 전부 원문에 있는 경우. 실행 46 에서
  // "다이마루 백화점 명품 손수건" 이 여기 해당했다 — 설명란에 "다이마루
  // 백화점" 과 "명품 손수건" 이 따로 있었는데 그 사이에 다른 말이 끼어
  // 통짜 찾기가 실패했다. 내용은 원문에 다 있는데 잡음만 냈다.
  //
  // in_source 와 합치지 않는다. 흔한 단어만으로 지어낸 이름도 이 검사는
  // 통과하므로, 더 약한 판정으로 따로 표시해 사람이 보게 둔다.
  const parts = tokensOf(headRaw);
  if (parts.length >= 2 && parts.every(p => hay.includes(p))) return 'parts_in_source';

  return 'not_in_source';
}
""".strip()

JS_SOURCECHECK = (r"""
const fs = require('fs');
const sb = $json.storyboard ?? {};
const items = sb.items ?? [];
const runDir = $('선택 정리').first().json.runDir;

// Does every item Claude reports actually appear in the material we fetched?
//
// This replaces an external place lookup. Both free options were tested and
// both fail the same way: Nominatim answered "유니버설 스튜디오 재팬" with a
// river in Russia, and Tavily returned Tabelog and osaka-info.jp pages for
// shop names that were invented for the test. A check that says "실재 확인"
// about a made-up shop is worse than no check at all.
//
// So ask the question we can actually answer. Every invention we have caught
// -- the matcha-jp cards, the guessed "(케아나나데시코 모공 쌀팩)" -- was a
// name that was not in the source text. This catches those, for products as
// well as places, with no API. in_source cannot false-positive; the weaker
// parts_in_source can, which is why it is reported as its own verdict.
// Its limit is equally clear: it cannot tell whether the SOURCE is wrong.
// That axis belongs to the evidence grades.
let sourceText = '';
try { sourceText = fs.readFileSync(runDir + '/source-text.txt', 'utf8'); } catch (e) { }
""" + JS_VERDICT + r"""
const itemChecks = items.map(i => {
  const name = String(i.name ?? '').trim();
  return {
    name,
    itemType: i.itemType ?? '',
    evidence: i.evidence ?? '',
    verdict: verdictOf(name, sourceText),
  };
});

fs.writeFileSync(runDir + '/items-checked.json', JSON.stringify(itemChecks, null, 2), 'utf8');

return [{ json: { ...$json, itemChecks } }];
""").strip()

JS_SHOTS = r"""
const sb = $json.storyboard ?? {};
const items = sb.items ?? [];
const checks = $json.itemChecks ?? [];

// Only look for shots for items a card may actually use.
const byName = new Map(checks.map(c => [c.name, c.verdict]));
const usable = items.filter(i => {
  const ev = String(i.evidence ?? '');
  const vd = byName.get(String(i.name ?? '').trim());
  return ['official', 'confirmed', 'weak'].includes(ev)
    && ['in_source', 'head_only', 'parts_in_source'].includes(vd);
});

// Same reason as elsewhere: n8n skips a node that gets no items, which would
// stall the chain. One throwaway search out of 1000/month costs nothing.
// ponytail: 빈 조회 1건. 크레딧이 빠듯해지면 IF 분기로 교체
if (!usable.length) {
  return [{ json: { storyboard: sb, itemChecks: checks, shotFor: null, shotQuery: 'placeholder', skip: true } }];
}

return usable.map(i => ({
  json: {
    storyboard: sb,
    itemChecks: checks,
    shotFor: i.name,
    shotQuery: String(i.name).split(/[(（]/)[0].trim() + ' 제품',
    skip: false,
  },
}));
""".strip()

JS_APPROVE_FORM = r"""
const fs = require('fs');

// 장소 확인 runs once per place, so $json here is a Maps response, not the
// storyboard. Take both from 장소 추출, which carries the storyboard on every
// item it emits and lines up index-for-index with the lookups.
// 제품컷 검색 runs once per item, so $json here is a Tavily response. Take the
// storyboard from 제품컷 찾기, which carries it on every item it emits and
// lines up index-for-index with the searches.
const asked = $('제품컷 찾기').all().map(i => i.json);
const sb = asked[0]?.storyboard ?? {};
const cards = sb.cards ?? [];
if (!cards.length) throw new Error('스토리보드에 카드가 없습니다.');

const itemChecks = asked[0]?.itemChecks ?? [];
const runDir = $('선택 정리').first().json.runDir;

let found = [];
try { found = $('제품컷 검색').all().map(i => i.json); } catch (e) { /* node errored */ }

// Tavily returns images for anything, including names that do not exist --
// a probe for an invented product came back with 상쾌환 packs. So keep the
// AI description next to each image: when it names a different product, the
// mismatch is visible. This finds candidates; it does not clear their rights.
const hostOf = u => (String(u ?? '').match(/^https?:\/\/([^/?#]+)/i) || ['', ''])[1].replace(/^www\./i, '');
const shots = [];
asked.forEach((a, idx) => {
  if (a.skip || !a.shotFor) return;
  const j = found[idx] ?? {};
  const imgs = (j.images ?? []).slice(0, 3).map(x => (typeof x === 'string')
    ? { url: x, desc: '' }
    : { url: x.url ?? '', desc: String(x.description ?? '') });
  shots.push({
    name: a.shotFor,
    query: a.shotQuery,
    images: imgs,
    pages: (j.results ?? []).slice(0, 3).map(r => ({ url: r.url ?? '', host: hostOf(r.url) })),
  });
});

// Park these on disk so 저장 reads back exactly what was approved, instead of
// guessing which run of this node the revision loop landed on.
fs.writeFileSync(runDir + '/storyboard-latest.json', JSON.stringify(sb, null, 2), 'utf8');
fs.writeFileSync(runDir + '/product-shots.json', JSON.stringify(shots, null, 2), 'utf8');

const he = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;')
  .replace(/>/g, '&gt;').replace(/"/g, '&quot;');

const html = '<p><b>독자</b> ' + he(sb.audience) + '<br><b>앵글</b> ' + he(sb.angle) + '</p>'
  + ((sb.hooks ?? []).length
      ? '<p><b>후킹 문구 후보</b></p><ul>' + sb.hooks.map(h => '<li>' + he(h) + '</li>').join('') + '</ul>'
      : '')
  + (shots.length
      ? '<p><b>제품컷 후보</b> — 이용 조건은 출처 페이지에서 직접 확인하세요</p>'
        + shots.map(s => '<p>' + he(s.name) + '<br>'
            + (s.images.length
                ? s.images.map(im => '<img src="' + he(im.url) + '" alt="' + he(s.name) + '">'
                    + (im.desc ? '<br><span>' + he(im.desc.slice(0, 90)) + '</span>' : '')).join('<br>')
                : '이미지 못 찾음')
            + (s.pages.length ? '<br>출처: ' + s.pages.map(pg =>
                '<a href="' + he(pg.url) + '" target="_blank">' + he(pg.host) + '</a>').join(' · ') : '')
            + '</p>').join('')
      : '')
  + (() => {
      // 영상 분석 결과 한 줄. 키가 틀렸거나 한도를 넘겼으면 여기서 바로 보인다.
      let sf = null;
      try { sf = JSON.parse(fs.readFileSync(runDir + '/sources-fetched.json', 'utf8')); } catch (e) { }
      if (!sf) return '';
      const ok = (sf.watched ?? []).length;
      const errs = sf.videoErrors ?? [];
      const skips = sf.videoSkipped ?? [];
      if (!ok && !errs.length && !skips.length) return '';
      return '<p><b>영상 분석</b> — Gemini 가 영상을 직접 본 결과</p><ul>'
        + '<li>반영 ' + ok + '편</li>'
        + errs.map(e => '<li>실패: ' + he(e) + '</li>').join('')
        + skips.map(e => '<li>건너뜀: ' + he(e) + '</li>').join('')
        + '</ul>';
    })()
  + (itemChecks.length
      ? '<p><b>원문 대조</b> — 품목명이 우리가 가져온 원문에 실제로 있는지</p><ul>'
        + itemChecks.map(v => '<li>' + he(v.name) + ' — '
            + (v.verdict === 'in_source'     ? '원문에 있음'
             : v.verdict === 'head_only'     ? '<b>괄호 앞만 원문에 있음 — 괄호 안은 모델 추측일 수 있음</b>'
             : v.verdict === 'parts_in_source' ? '단어는 전부 원문에 있으나 이 이름 그대로는 없음 — 모델이 조합한 이름'
             : v.verdict === 'not_in_source' ? '<b>원문에 없음 — 카드에 쓰지 마세요</b>'
             : v.verdict === 'no_source'     ? '원문을 못 가져와 대조 불가'
             : '이름 없음')
            + '</li>').join('') + '</ul>'
      : '')
  + ((sb.items ?? []).length
      ? '<p><b>품목 교차 확인</b></p><ul>' + sb.items.map(i =>
          '<li>' + he(i.name) + ' — <b>' + he(i.evidence) + '</b>'
          + (i.itemType ? ' · ' + he(i.itemType) : '')
          + (i.affiliate ? ' · <b>제휴/광고 출처</b>' : '')
          + ((i.sources ?? []).length ? ' (' + i.sources.length + '곳)' : '') + '</li>').join('') + '</ul>'
      : '')
  + cards.map(c => '<p><b>' + he(c.no) + '. [' + he(c.role) + '] ' + he(c.title) + '</b><br>'
      + he(c.body)
      + '<br><b>근거</b> ' + he(c.source)
      + '<br><b>그림 계획</b> ' + he(c.image_plan) + '</p>').join('');

const fields = [
  { fieldLabel: '스토리보드 ' + cards.length + '장', fieldType: 'html', html },
  { fieldLabel: '진행 여부', fieldName: 'decision', fieldType: 'radio',
    fieldOptions: { values: [{ option: '승인' }, { option: '수정 요청' }] }, requiredField: true },
  { fieldLabel: '수정 지시 (수정 요청일 때만)', fieldName: 'revision', fieldType: 'textarea' },
];

return [{ json: { ...asked[0], shots, formFields: JSON.stringify(fields).split('$').join('$$') } }];
""".strip()

JS_REVISE = r"""
const fs = require('fs');
const ctx = $('응답 파싱').first().json;

// Cap the revision loop. It runs back into Claude: 심층조사, and each pass is
// a paid call with no natural end — a user who keeps clicking 수정 요청 can
// spin it forever. The storyboard shown on screen is already on disk, so
// stopping here loses nothing but the final script.md / sources.md.
const MAX_REVISIONS = 3;
if ($runIndex >= MAX_REVISIONS) {
  throw new Error('수정 요청이 ' + MAX_REVISIONS + '회를 넘었습니다. 마지막 스토리보드는 '
    + $('응답 파싱').first().json.runDir + '/storyboard-latest.json 에 있습니다. '
    + '방향을 바꾸려면 주제나 후보를 다시 골라 새로 실행하세요.');
}

const instruction = String($json.revision ?? $json['수정 지시 (수정 요청일 때만)'] ?? '').trim();
if (!instruction) throw new Error('수정 요청을 골랐으면 수정 지시를 적어 주세요.');

const prompt = [
  '방금 제안한 스토리보드를 아래 지시대로 고쳐라.',
  '',
  '수정 지시: ' + instruction,
  '',
  '지시와 무관한 카드는 그대로 둔다. 규칙은 그대로다.',
  '{"status":"result","storyboard":{...}} JSON 하나만 출력하라.',
].join('\n');

const promptFile = ctx.runDir + '/prompt-revision-' + Date.now() + '.txt';
fs.writeFileSync(promptFile, prompt, 'utf8');
return [{ json: { ...ctx, promptFile } }];
""".strip()

JS_SAVE = r"""
const fs = require('fs');
const ctx = $('응답 파싱').first().json;
const sb = JSON.parse(fs.readFileSync(ctx.runDir + '/storyboard-latest.json', 'utf8'));
let itemChecks = [];
try {
  itemChecks = JSON.parse(fs.readFileSync(ctx.runDir + '/items-checked.json', 'utf8'));
} catch (e) { /* older run, or no items */ }
let shots = [];
try {
  shots = JSON.parse(fs.readFileSync(ctx.runDir + '/product-shots.json', 'utf8'));
} catch (e) { /* no usable items to look up */ }
const cards = sb.cards ?? [];
const chosen = ctx.chosen ?? [];

fs.writeFileSync(ctx.runDir + '/storyboard.json', JSON.stringify(sb, null, 2), 'utf8');

const script = [
  '# ' + ctx.topic,
  '',
  '- 독자: ' + (sb.audience ?? ''),
  '- 앵글: ' + (sb.angle ?? ''),
  '- 조사 기준: ' + ctx.researchedAt + ' 기준 최근 ' + ctx.days + '일',
  '',
  ...cards.map(c => [
    '## ' + c.no + '. [' + c.role + '] ' + c.title,
    '',
    String(c.body ?? ''),
    '',
    '- 근거: ' + String(c.source ?? ''),
    '- 그림 계획: ' + String(c.image_plan ?? ''),
    '',
  ].join('\n')),
].join('\n');
fs.writeFileSync(ctx.runDir + '/script.md', script, 'utf8');

const sources = [
  '# 출처',
  '',
  '조사 기준: ' + ctx.researchedAt + ' 기준 최근 ' + ctx.days + '일',
  '',
  '## 선택한 후보',
  '',
  ...chosen.map(c => '- [' + c.title + '](' + c.url + ') — ' + c.source
    + (c.channel ? ' · ' + c.channel : '') + ' · ' + (c.publishedAt ?? '날짜 미확인')),
  '',
  '## 카드별 근거',
  '',
  ...cards.map(c => '- ' + c.no + '. ' + String(c.source ?? '')),
  '',
  '## 품목 교차 확인',
  '',
  ...((sb.items ?? []).length
    ? (sb.items ?? []).map(i => '- ' + i.name + ' — ' + i.evidence
        + (i.affiliate ? ' · 제휴/광고 콘텐츠 출처' : '')
        + (i.query_used ? ' · 검색어: ' + i.query_used : '')
        + ((i.sources ?? []).length ? '\n' + i.sources.map(u => '  - ' + u).join('\n') : ''))
    : ['(품목 추출 없음)']),
  '',
  'official = 관광국·기관·브랜드 공식 / confirmed = 블로그·기사 2곳 이상 / weak = 1곳 /',
  'retail_only = 쇼핑몰 페이지만 / unconfirmed = 못 찾음',
  '',
  '## 원문 대조',
  '',
  '품목명이 실제로 가져온 원문에 있었는지. 외부 조회가 아니라 source-text.txt 와의 대조라',
  '오탐이 없다. 대신 원문 자체가 틀린 경우는 잡지 못한다 — 그건 위 등급이 담당한다.',
  '',
  ...(itemChecks.length
    ? itemChecks.map(v => '- ' + v.name + ' — ' + (
        v.verdict === 'in_source'     ? '원문에 있음'
      : v.verdict === 'head_only'     ? '괄호 앞만 원문에 있음 (괄호 안은 모델 추측 가능성)'
      : v.verdict === 'parts_in_source' ? '단어는 전부 원문에 있으나 이 이름 그대로는 없음 (모델이 조합)'
      : v.verdict === 'not_in_source' ? '원문에 없음'
      : v.verdict === 'no_source'     ? '원문을 못 가져와 대조 불가'
      : '이름 없음'))
    : ['(품목 없음)']),
  '',
  '## 제품컷 후보',
  '',
  '검색으로 모은 후보일 뿐이며 이용 허락을 받은 것이 아니다. 출처 페이지에서 조건을',
  '직접 확인하고 쓸 것. 설명문이 다른 제품을 가리키면 검색이 빗나간 것이다.',
  '',
  ...(shots.length
    ? shots.flatMap(sh => ['- ' + sh.name + ' (검색어: ' + sh.query + ')']
        .concat((sh.images ?? []).map(im => '  - ' + im.url + (im.desc ? '\n    ' + im.desc : '')))
        .concat((sh.pages ?? []).length ? ['  - 출처: ' + sh.pages.map(pg => pg.host).join(', ')] : []))
    : ['(대상 품목 없음)']),
  '',
  '이미지 생성과 카드 렌더링은 아직 없습니다. 다음 단계에서 이 파일에 기록을 추가합니다.',
].join('\n');
fs.writeFileSync(ctx.runDir + '/sources.md', sources, 'utf8');

return [{ json: {
  runDir: ctx.runDir, cards: cards.length,
  files: 'storyboard.json, script.md, sources.md, selection.json, candidates-raw.json',
} }];
""".strip()

# Small enough to stay inline; radio/textarea labels get escaped by n8n itself,
# and `why` only needs its angle brackets stripped for the html field.
JS_QUESTION_FORM = (
    "={{ JSON.stringify(["
    "{fieldLabel:'왜 묻는지', fieldType:'html', html:'<p>' + String($json.why || '').replace(/[<>]/g,'') + '</p>'},"
    "{fieldLabel: String($json.question || '어느 쪽으로 갈까요?'), fieldName:'answer', fieldType:'radio',"
    " fieldOptions:{values: ($json.options || []).map(o => ({option: String(o)}))}, requiredField:true},"
    "{fieldLabel:'직접 입력 (위 선택 대신)', fieldName:'answerFree', fieldType:'textarea'}"
    "]).split('$').join('$$') }}"
)

# ------------------------------------------------------------------- helpers

_seq = [0]


def node(name, ntype, tv, params, pos, extra=None):
    _seq[0] += 1
    n = {'parameters': params, 'type': ntype, 'typeVersion': tv, 'position': pos,
         'id': 'cafe0000-0000-4000-8000-%012d' % _seq[0], 'name': name}
    if extra:
        n.update(extra)
    return n


def code(name, js, pos):
    return node(name, 'n8n-nodes-base.code', 2, {'jsCode': js}, pos)


def form_page(name, json_output, pos, button, css=None):
    opts = {'buttonLabel': button}
    if css:
        opts['customCss'] = css
    return node(name, 'n8n-nodes-base.form', 2.5, {
        'operation': 'page', 'defineForm': 'json', 'jsonOutput': json_output,
        'options': opts,
    }, pos, {'webhookId': 'cardnews-form-%d' % (_seq[0] + 1)})


def cond_equals(left, right):
    return {'options': {'caseSensitive': True, 'leftValue': '', 'typeValidation': 'strict', 'version': 2},
            'conditions': [{'id': 'cond-%d' % (_seq[0] + 1), 'leftValue': left, 'rightValue': right,
                            'operator': {'type': 'string', 'operation': 'equals'}}],
            'combinator': 'and'}


# --------------------------------------------------------------------- nodes

nodes = [
    node('카드뉴스 시작', 'n8n-nodes-base.formTrigger', 2.6, {
        'path': 'cardnews',
        'formTitle': '카드뉴스 만들기',
        'formDescription': '주제를 넣으면 유튜브와 웹에서 자료를 모아 옵니다. 무엇을 쓸지는 다음 화면에서 직접 고릅니다.',
        'formFields': {'values': [
            {'fieldLabel': '주제', 'fieldName': 'topic',
             'placeholder': '여행 기념품 추천', 'requiredField': True},
            {'fieldLabel': '조사 기간', 'fieldName': 'period', 'fieldType': 'dropdown',
             'fieldOptions': {'values': [{'option': '최근 7일'}, {'option': '최근 30일'}]},
             'requiredField': True},
            {'fieldLabel': '용도와 독자', 'fieldName': 'purpose', 'fieldType': 'textarea',
             'placeholder': '캐리어 플랫폼 인스타 계정 — 여행 준비하는 20~30대'},
        ]},
        'options': {'buttonLabel': '조사 시작'},
    }, [-240, 0], {'webhookId': 'cardnews-start-form'}),

    code('준비', JS_PREP, [-20, 0]),

    node('유튜브 검색', 'n8n-nodes-base.httpRequest', 4.5, {
        'url': 'https://www.googleapis.com/youtube/v3/search',
        'authentication': 'genericCredentialType', 'genericAuthType': 'httpQueryAuth',
        'sendQuery': True,
        'queryParameters': {'parameters': [
            {'name': 'part', 'value': 'snippet'},
            {'name': 'type', 'value': 'video'},
            {'name': 'maxResults', 'value': '25'},
            {'name': 'order', 'value': 'relevance'},
            {'name': 'regionCode', 'value': 'KR'},
            {'name': 'relevanceLanguage', 'value': 'ko'},
            {'name': 'q', 'value': '={{ $json.topic }}'},
            {'name': 'publishedAfter', 'value': '={{ $json.publishedAfter }}'},
        ]},
        'options': {},
    }, [200, -120], {'onError': 'continueRegularOutput',
                     'retryOnFail': True, 'maxTries': 3, 'waitBetweenTries': 2000}),

    node('웹 검색', 'n8n-nodes-base.httpRequest', 4.5, {
        'method': 'POST',
        'url': 'https://api.tavily.com/search',
        'authentication': 'genericCredentialType', 'genericAuthType': 'httpHeaderAuth',
        'sendBody': True, 'specifyBody': 'json',
        'jsonBody': "={{ JSON.stringify({ query: $json.topic, language: 'ko',"
                    " filter_by_language: true, time_range: $json.tavilyRange,"
                    " max_results: 20, search_depth: 'basic' }) }}",
        'options': {},
    }, [200, 120], {'onError': 'continueRegularOutput',
                    'retryOnFail': True, 'maxTries': 3, 'waitBetweenTries': 2000}),

    node('소스 합치기', 'n8n-nodes-base.merge', 3.2,
         {'mode': 'append', 'numberInputs': 2, 'options': {}}, [420, 0]),

    code('후보 정리', JS_CANDIDATES, [640, 0]),
    node('Claude: 후보 평가', 'n8n-nodes-base.executeCommand', 1, {'command': cmd()}, [860, 0]),

    # 후보 순위에 실제 숫자를 하나 붙인다. 이 단계 Claude 는 웹 검색을 안 해서
    # "유행" 을 판단할 근거가 없다. videos.list 는 1 유닛이라(search.list 는
    # 100) 부담이 없고, 길이도 같이 받아 20분 넘는 영상을 미리 표시한다.
    node('후보 조회수', 'n8n-nodes-base.httpRequest', 4.5, {
        'url': 'https://www.googleapis.com/youtube/v3/videos',
        'authentication': 'genericCredentialType', 'genericAuthType': 'httpQueryAuth',
        'sendQuery': True,
        'queryParameters': {'parameters': [
            {'name': 'part', 'value': 'statistics,contentDetails'},
            {'name': 'id', 'value': "={{ $('후보 정리').first().json.candidateVideoIds }}"},
        ]},
        'options': {},
    }, [970, 0], {'onError': 'continueRegularOutput',
                  'retryOnFail': True, 'maxTries': 3, 'waitBetweenTries': 2000}),

    code('후보 화면 만들기', JS_PICK_FORM, [1080, 0]),
    form_page('후보 선택', '={{ $json.formFields }}', [1300, 0], '이걸로 만들기', PICK_CSS),
    code('선택 정리', JS_PICKED, [1520, 0]),

    # Fetch the sources ourselves. Asking the model to open these pages does
    # not work -- Naver and Instagram refuse the fetch, YouTube needs JS --
    # and both of these endpoints are covered by credentials we already have.
    node('유튜브 원문', 'n8n-nodes-base.httpRequest', 4.5, {
        'url': 'https://www.googleapis.com/youtube/v3/videos',
        'authentication': 'genericCredentialType', 'genericAuthType': 'httpQueryAuth',
        'sendQuery': True,
        'queryParameters': {'parameters': [
            # contentDetails 는 길이 때문에 필요하다. 영상 분석 대상이 너무 긴 영상을
            # 걸러 낼 때 쓴다.
            {'name': 'part', 'value': 'snippet,statistics,contentDetails'},
            {'name': 'id', 'value': '={{ $json.videoIds }}'},
        ]},
        'options': {},
    }, [1740, -110], {'onError': 'continueRegularOutput',
                      'retryOnFail': True, 'maxTries': 3, 'waitBetweenTries': 2000}),

    node('웹 원문', 'n8n-nodes-base.httpRequest', 4.5, {
        'method': 'POST',
        'url': 'https://api.tavily.com/extract',
        'authentication': 'genericCredentialType', 'genericAuthType': 'httpHeaderAuth',
        'sendBody': True, 'specifyBody': 'json',
        'jsonBody': "={{ JSON.stringify({ urls: $('선택 정리').first().json.webUrls,"
                    " extract_depth: 'basic' }) }}",
        'options': {},
    }, [1960, -110], {'onError': 'continueRegularOutput',
                      'retryOnFail': True, 'maxTries': 3, 'waitBetweenTries': 2000}),

    code('영상 분석 대상', JS_VIDEO, [1740, 90]),

    # 유튜브 URL 을 그대로 넘기면 Gemini 가 영상을 직접 본다. 무료 한도는
    # 하루 8시간, 요청당 영상 1개, 공개 영상만.
    node('제미나이 영상 분석', 'n8n-nodes-base.httpRequest', 4.5, {
        'method': 'POST',
        'url': 'https://generativelanguage.googleapis.com/v1beta/interactions',
        'authentication': 'genericCredentialType', 'genericAuthType': 'httpHeaderAuth',
        'sendHeaders': True,
        'headerParameters': {'parameters': [
            # 리비전을 못 박는다. 이 API 는 2026-05 에 출력이 steps[] 로 옮겨
            # 가는 파괴적 변경이 있었다. 안 박으면 이미 배포된 워크플로 밑에서
            # 응답 모양이 또 바뀔 수 있다.
            {'name': 'Api-Revision', 'value': '2026-05-20'},
        ]},
        'sendBody': True, 'specifyBody': 'json',
        'jsonBody': '={{ JSON.stringify($json.body) }}',
        'options': {
            # 영상 한 편에 1분 넘게 걸리기도 한다.
            'timeout': 300000,
            # 텍스트로 받아 직접 파싱한다. 이 엔드포인트는 generateContent 와
            # 달리 최상위가 JSON 배열이다(chunked 스트리밍). 키 없이 호출해
            # 확인했다: 오류도 [{...}] 로 온다. n8n 은 최상위 배열을 아이템
            # 여러 개로 쪼개므로, 그대로 두면 영상 분석 대상과의 인덱스 짝이
            # 깨진다. 텍스트면 호출당 정확히 아이템 1개다.
            'response': {'response': {'responseFormat': 'text'}},
        },
    }, [1960, 90], {'onError': 'continueRegularOutput',
                    'retryOnFail': True, 'maxTries': 2, 'waitBetweenTries': 5000}),

    code('심층조사 지시', JS_DEEP, [2180, -110]),
    node('Claude: 심층조사', 'n8n-nodes-base.executeCommand', 1, {'command': cmd(session=True)}, [2400, -110]),
    code('응답 파싱', JS_PARSE, [2620, -110]),

    node('질문인가?', 'n8n-nodes-base.if', 2.3,
         {'conditions': cond_equals('={{ $json.status }}', 'need_input'), 'options': {}}, [2840, -110]),

    form_page('질문', JS_QUESTION_FORM, [3060, -300], '답변 제출'),
    code('답변 전달', JS_ANSWER, [3280, -300]),

    code('원문 대조', JS_SOURCECHECK, [3060, 60]),

    code('제품컷 찾기', JS_SHOTS, [3280, 60]),

    # Tavily returns image URLs plus an AI description of each. One call per
    # item, which is what an n8n HTTP node does with multiple input items.
    node('제품컷 검색', 'n8n-nodes-base.httpRequest', 4.5, {
        'method': 'POST',
        'url': 'https://api.tavily.com/search',
        'authentication': 'genericCredentialType', 'genericAuthType': 'httpHeaderAuth',
        'sendBody': True, 'specifyBody': 'json',
        'jsonBody': "={{ JSON.stringify({ query: $json.shotQuery, max_results: 5,"
                    " search_depth: 'basic', include_images: true,"
                    " include_image_descriptions: true }) }}",
        'options': {},
    }, [3500, 60], {'onError': 'continueRegularOutput',
                    'retryOnFail': True, 'maxTries': 3, 'waitBetweenTries': 2000}),

    code('스토리보드 화면 만들기', JS_APPROVE_FORM, [3720, 60]),
    form_page('스토리보드 승인', '={{ $json.formFields }}', [3940, 60], '제출'),

    node('승인인가?', 'n8n-nodes-base.if', 2.3,
         {'conditions': cond_equals("={{ $json.decision ?? $json['진행 여부'] }}", '승인'),
          'options': {}}, [4160, 60]),

    code('저장', JS_SAVE, [4380, -40]),
    code('수정 지시', JS_REVISE, [4380, 200]),

    node('완료', 'n8n-nodes-base.form', 2.5, {
        'operation': 'completion', 'respondWith': 'text',
        'completionTitle': '카드뉴스 원고 완성',
        'completionMessage': "={{ '카드 ' + $json.cards + '장.\\n저장 위치: ' + $json.runDir"
                             " + '\\n파일: ' + $json.files }}",
        'options': {},
    }, [4600, -40], {'webhookId': 'cardnews-form-done'}),
]


def m(target, idx=0):
    return [{'node': target, 'type': 'main', 'index': idx}]


connections = {
    '카드뉴스 시작': {'main': [m('준비')]},
    '준비': {'main': [[{'node': '유튜브 검색', 'type': 'main', 'index': 0},
                       {'node': '웹 검색', 'type': 'main', 'index': 0}]]},
    '유튜브 검색': {'main': [m('소스 합치기', 0)]},
    '웹 검색': {'main': [m('소스 합치기', 1)]},
    '소스 합치기': {'main': [m('후보 정리')]},
    '후보 정리': {'main': [m('Claude: 후보 평가')]},
    'Claude: 후보 평가': {'main': [m('후보 조회수')]},
    '후보 조회수': {'main': [m('후보 화면 만들기')]},
    '후보 화면 만들기': {'main': [m('후보 선택')]},
    '후보 선택': {'main': [m('선택 정리')]},
    '선택 정리': {'main': [m('유튜브 원문')]},
    '유튜브 원문': {'main': [m('웹 원문')]},
    '웹 원문': {'main': [m('영상 분석 대상')]},
    '영상 분석 대상': {'main': [m('제미나이 영상 분석')]},
    '제미나이 영상 분석': {'main': [m('심층조사 지시')]},
    '심층조사 지시': {'main': [m('Claude: 심층조사')]},
    'Claude: 심층조사': {'main': [m('응답 파싱')]},
    '응답 파싱': {'main': [m('질문인가?')]},
    '질문인가?': {'main': [m('질문'), m('원문 대조')]},
    '원문 대조': {'main': [m('제품컷 찾기')]},
    '제품컷 찾기': {'main': [m('제품컷 검색')]},
    '제품컷 검색': {'main': [m('스토리보드 화면 만들기')]},
    '질문': {'main': [m('답변 전달')]},
    '답변 전달': {'main': [m('Claude: 심층조사')]},
    '스토리보드 화면 만들기': {'main': [m('스토리보드 승인')]},
    '스토리보드 승인': {'main': [m('승인인가?')]},
    '승인인가?': {'main': [m('저장'), m('수정 지시')]},
    '수정 지시': {'main': [m('Claude: 심층조사')]},
    '저장': {'main': [m('완료')]},
}

wf = {
    'id': 'cardnewsMvp0001',
    'name': '카드뉴스 MVP — 조사에서 스토리보드까지',
    'active': False,
    'nodes': nodes,
    'connections': connections,
    'settings': {'executionOrder': 'v1'},
    'pinData': {},
}

# sanity: every connection endpoint must be a real node
names = {n['name'] for n in nodes}
for src, spec in connections.items():
    assert src in names, 'unknown source node: %s' % src
    for branch in spec['main']:
        for link in branch:
            assert link['node'] in names, 'unknown target node: %s' % link['node']

# customCss 가 n8n 의 sanitizeCustomCss 를 통과하는지 확인한다. 이 함수는
# allowedTags 를 비운 sanitize-html 을 돌린 뒤 &gt; 만 > 로 되돌린다. 걸리는
# 문자를 쓰면 CSS 가 조용히 잘려서 레이아웃만 안 먹는다 — 오류는 안 난다.
import subprocess, tempfile, os as _os

_CSS_JS = r"""
const path = require('path');
const fs = require('fs');
const base = path.join(process.env.LOCALAPPDATA, 'npm-cache', '_npx');
// 캐시 폴더 이름은 npx 가 정하므로 sanitize-html 이 있는 곳을 찾아 쓴다.
let mod = null;
for (const d of fs.readdirSync(base)) {
  const p = path.join(base, d, 'node_modules', 'sanitize-html');
  if (fs.existsSync(p)) { mod = p; break; }
}
if (!mod) { console.log('SKIP sanitize-html 을 찾지 못했습니다'); process.exit(0); }
const sanitizeHtml = require(mod);
const css = fs.readFileSync(process.argv[2], 'utf8');
const out = sanitizeHtml(css, { allowedTags: [], allowedAttributes: {} })
  .replace(/&gt;/g, '>').replace(/&amp;(?!(?:lt|gt|amp);)/g, '&');
if (out === css) { console.log('OK'); process.exit(0); }
let i = 0;
while (i < Math.min(css.length, out.length) && css[i] === out[i]) i++;
console.log('BAD ' + css.length + ' -> ' + out.length);
console.log('  원본 …' + css.slice(Math.max(0, i - 50), i + 50));
console.log('  결과 …' + out.slice(Math.max(0, i - 50), i + 50));
process.exit(1);
"""

_cf = tempfile.NamedTemporaryFile('w', suffix='.css', delete=False, encoding='utf-8')
_cf.write(PICK_CSS)
_cf.close()
_jf = tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8')
_jf.write(_CSS_JS)
_jf.close()
_r = subprocess.run(['node', _jf.name, _cf.name], capture_output=True, text=True, encoding='utf-8')
_os.unlink(_cf.name)
_os.unlink(_jf.name)
_msg = (_r.stdout or '').strip()
if _r.returncode != 0:
    print(_msg or _r.stderr)
    raise SystemExit('customCss 가 n8n 검사기를 통과하지 못했습니다 — 쓰지 않았습니다.')
# node 가 없거나 캐시를 못 찾으면 검사를 못 한 것이지 CSS 가 나쁜 게 아니다.
print('customCss 검사: %s' % (_msg or '검사기 없음 (건너뜀)'))

# Run the verdict rule against fixtures, using the SAME snippet the workflow
# embeds. 실행 46 에서 조합된 이름이 not_in_source 로 찍혀 잡음이 됐다.
# 판정이 조용히 느슨해지거나 빡빡해지면 화면의 경고가 믿을 수 없게 된다.
import subprocess, tempfile, os as _os

VERDICT_CASES = [
    # (이름, 원문, 기대 판정)
    ('고베 푸딩', '고베 푸딩은 효고현의 대표 기념품이다', 'in_source'),
    ('멜라노CC', '멜라노 cc 앰플을 샀다', 'in_source'),            # 띄어쓰기·대소문자 무시
    ('VC100 마스크팩 (퀄리티퍼스트 초이스)', 'VC100 마스크팩을 대량으로 샀다', 'head_only'),
    # 실행 46 의 그 항목. 설명란에 두 조각이 따로 있고 사이에 다른 말이 낀다.
    ('다이마루 백화점 명품 손수건 (BOSS·DAKS)',
     '오사카 다이마루 백화점 1층 잡화. 남성은 BOSS·DAKS 명품 손수건 추천', 'parts_in_source'),
    # 단어 하나라도 없으면 조합으로 봐주지 않는다.
    ('오사카 한정 킷캣', '오사카 다이마루 백화점 손수건을 샀다', 'not_in_source'),
    ('흐린날 젤리스틱', '고베 푸딩과 오사카 치즈 브륄레를 샀다', 'not_in_source'),
    ('고베 푸딩', '', 'no_source'),
    ('', '아무 원문이나', 'empty'),
]

_test_js = (JS_VERDICT + '\nconst CASES = ' + json.dumps(VERDICT_CASES, ensure_ascii=False) + ';\n' + r"""
let bad = 0;
for (const [name, source, want] of CASES) {
  const got = verdictOf(name, source);
  if (got !== want) {
    bad++;
    console.error('판정 불일치: "' + name + '" -> ' + got + ' (기대: ' + want + ')');
  }
}
if (bad) { console.error(bad + '건 불일치'); process.exit(1); }
""")
_fh = tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8')
_fh.write(_test_js)
_fh.close()
_r = subprocess.run(['node', _fh.name], capture_output=True, text=True, encoding='utf-8')
_os.unlink(_fh.name)
if _r.returncode != 0:
    print(_r.stderr or _r.stdout)
    raise SystemExit('원문 대조 판정 검사 실패 — 쓰지 않았습니다.')
print('원문 대조 판정 검사 %d건 통과' % len(VERDICT_CASES))

# Syntax-check every Code node before writing. A broken jsCode otherwise only
# surfaces three minutes into a live run as "Unexpected string".
import subprocess, tempfile
bad = []
for n in nodes:
    js = n.get('parameters', {}).get('jsCode')
    if not js:
        continue
    # Code nodes use a top-level return, which is only legal inside a function.
    wrapped = '(function(){\n' + js + '\n})();\n'
    fh = tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8')
    fh.write(wrapped)
    fh.close()
    r = subprocess.run(['node', '--check', fh.name], capture_output=True, text=True)
    os.unlink(fh.name)
    if r.returncode != 0:
        first = [l for l in (r.stderr or '').splitlines() if l.strip()][:4]
        bad.append((n['name'], '\n    '.join(first)))
if bad:
    for name, err in bad:
        print('JS 문법 오류 [%s]\n    %s' % (name, err))
    raise SystemExit('Code 노드 %d개에 문법 오류가 있어 쓰지 않았습니다.' % len(bad))

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with io.open(OUT, 'w', encoding='utf-8') as fh:
    json.dump(wf, fh, ensure_ascii=False, indent=2)
print('wrote %s  (%d nodes)' % (OUT, len(nodes)))
