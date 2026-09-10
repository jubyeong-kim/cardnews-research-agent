# -*- coding: utf-8 -*-
"""Builds workflows/cardnews-mvp.json. Keeps the embedded JS readable."""
import json, io, os

ROOT = 'C:/Users/jb660/Desktop/project_2/n8n'
ASK  = ROOT + '/scripts/ask-claude.ps1'
RUNS = ROOT + '/runs'
OUT  = ROOT + '/workflows/cardnews-mvp.json'


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

if (!candidates.length) {
  throw new Error('후보가 0개입니다. 검색 오류: ' + (sourceErrors.join(' / ')
    || '없음 — 검색은 됐으나 결과가 비었습니다. 주제를 바꾸거나 기간을 30일로 넓혀 보세요.'));
}

const prompt = [
  '너는 카드뉴스 조사 보조다. 아래는 "' + prep.topic + '" 주제로 최근 ' + prep.days + '일 안에서 모은 후보다.',
  prep.purpose ? '이 카드뉴스의 용도와 독자: ' + prep.purpose : '',
  '',
  '각 후보마다 두 가지를 한 줄씩 붙여라.',
  '- value: 카드뉴스 소재로 고를 만한 이유',
  '- uncertainty: 제목과 요약만으로는 확인되지 않는 점 (날짜 미확인, 광고·협찬 의심, 출처 불명 등)',
  '',
  '규칙:',
  '- 후보에 없는 사실을 지어내지 마라. 제목과 요약에서 읽히는 것만 쓴다.',
  '- 웹 검색을 하지 마라. 이 단계는 주어진 목록만 평가한다.',
  '- 아래 JSON 하나만 출력하고 다른 문장은 쓰지 마라.',
  '',
  '{"status":"result","candidates":[{"id":"c1","value":"...","uncertainty":"..."}]}',
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

return [{ json: { ...prep, candidates, sourceErrors, promptFile } }];
""".strip()

JS_PICK_FORM = r"""
const prev = $('후보 정리').first().json;

// ask-claude.ps1 hands over {sessionId, body} on success and
// {status:'error', reason, detail} on failure.
let out;
try { out = JSON.parse($json.stdout); }
catch (e) { throw new Error('래퍼 출력을 JSON으로 읽지 못했습니다: ' + String($json.stdout).slice(0, 400)); }
if (out.status === 'error') {
  throw new Error('Claude 실패 (' + out.reason + '): ' + String(out.detail ?? '').slice(0, 300));
}
const res = out.body ?? {};

const notes = new Map((res.candidates ?? []).map(c => [c.id, c]));
const candidates = prev.candidates.map(c => ({
  ...c,
  value: notes.get(c.id)?.value ?? '',
  uncertainty: notes.get(c.id)?.uncertainty ?? '',
}));

// The html field is the one place n8n does NOT escape for us.
const he = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;')
  .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const cut = (s, n) => { s = String(s ?? ''); return s.length > n ? s.slice(0, n - 1) + '…' : s; };

const head = '<p><b>조사 기준</b> ' + he(prev.researchedAt) + ' · 최근 ' + prev.days + '일 · 후보 ' + candidates.length + '개</p>'
  + (prev.sourceErrors.length
      ? '<p><b>소스 상태</b> ' + prev.sourceErrors.map(e => he(e)).join('<br>') + '</p>'
      : '');

const list = candidates.map(c =>
  '<p><b>' + he(c.id) + '. ' + he(c.title) + '</b><br>'
  + he(c.source) + (c.channel ? ' · ' + he(c.channel) : '')
  + ' · ' + he(c.publishedAt ?? '날짜 미확인')
  + (c.duplicates ? ' · 같은 소재 ' + c.duplicates + '건 묶임' : '')
  + '<br>' + he(c.summary)
  + (c.value ? '<br><b>고를 이유</b> ' + he(c.value) : '')
  + (c.uncertainty ? '<br><b>불확실</b> ' + he(c.uncertainty) : '')
  + '<br><a href="' + he(c.url) + '" target="_blank">원문 보기</a></p>'
).join('');

const fields = [
  { fieldLabel: '조사 결과', fieldType: 'html', html: head + list },
  {
    fieldLabel: '카드뉴스로 만들 것 (1~3개)', fieldName: 'picks', fieldType: 'checkbox',
    fieldOptions: { values: candidates.map(c => ({ option: cut(c.title, 60) + ' — ' + c.id })) },
    requiredField: true, limitSelection: 'range', minSelections: 1, maxSelections: 3,
  },
];

// n8n resolves this expression through String.replace, where $ starts a
// replacement pattern. Double it so a $ in a title survives intact.
const formFields = JSON.stringify(fields).split('$').join('$$');

return [{ json: { ...prev, candidates, sessionId: out.sessionId, formFields } }];
""".strip()

JS_PICKED = r"""
const fs = require('fs');
const prev = $('후보 화면 만들기').first().json;

const picked = $json.picks ?? $json['카드뉴스로 만들 것 (1~3개)'] ?? [];
const arr = Array.isArray(picked) ? picked : [picked];
// The option text carries the id as a suffix, because n8n form options allow
// exactly one key and have no separate value field.
const ids = arr.map(s => (String(s).match(/—\s*(c\d+)\s*$/) || [])[1]).filter(Boolean);
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
  if (body.trim()) verified++;
  blocks.push([
    '### ' + c.id + ' ' + c.title,
    'URL: ' + c.url,
    body.trim() ? '원문 본문(실제로 가져온 것):' : '원문 본문: 가져오지 못했습니다. 이 후보는 미확인으로 다룬다.',
    body.trim() ? cut(body, 8000) : '',
  ].filter(Boolean).join('\n'));
}

fs.writeFileSync(prev.runDir + '/sources-fetched.json', JSON.stringify({
  verified, total: chosen.length, extractFailed,
  blocks: blocks.map(b => b.length),
}, null, 2), 'utf8');

const prompt = [
  '너는 카드뉴스 편집자다. 아래 후보를 심층 조사하고 스토리보드를 만들어라.',
  '',
  '주제: ' + prev.topic,
  prev.purpose ? '용도와 독자: ' + prev.purpose : '',
  '조사 기준: ' + prev.researchedAt + ' 기준 최근 ' + prev.days + '일',
  '',
  '아래에 각 후보의 원문 본문을 실제로 가져와 붙였다 (' + verified + '/' + chosen.length + '건 확보).',
  '유튜브는 videos.list의 설명 전문, 웹은 Tavily로 추출한 페이지 본문이다.',
  '',
  blocks.join('\n\n'),
  '',
  '절차:',
  '1. 위 본문에서 구체적인 품목명을 뽑는다. 본문에 글자 그대로 있는 것만 뽑고, 정식 제품명을',
  '   추측해 괄호로 덧붙이지 마라. 확인되지 않은 제품 동일시는 지어내기와 같다.',
  '2. 각 품목을 WebSearch로 교차 확인한다. 검색어에 반드시 주제어("' + prev.topic + '")를 함께 넣는다.',
  '   품목명만 단독으로 검색하지 마라 — 쇼핑몰 상품페이지만 나와 검증이 되지 않는다.',
  '3. 근거 등급을 아래 기준대로 엄격히 매긴다.',
  '   - confirmed    : 서로 다른 개인 블로그·기사 2곳 이상이 이 주제 맥락에서 언급',
  '   - weak         : 그런 출처가 1곳',
  '   - retail_only  : 쇼핑몰 상품페이지만 나옴. 판매 사실만 확인된 것이며 추천 근거가 아니다',
  '   - unconfirmed  : 못 찾음',
  '4. 원문에 광고·협찬·제휴 표기가 있는지 확인한다. "광고", "협찬", "수수료를 제공받습니다",',
  '   "쇼핑 커넥트", "쿠팡 파트너스", "AD", "sponsored" 등이 보이면 그 후보에서 나온 품목은',
  '   반드시 제휴 콘텐츠 출처임을 밝히고 카드의 한계에도 적는다.',
  '5. 카드 본문에 단언으로 쓸 수 있는 것은 confirmed 와 weak 뿐이다. weak 은 "한 곳에서 언급"',
  '   처럼 범위를 밝혀 쓴다. retail_only 와 unconfirmed 는 카드의 주장 근거로 쓰지 마라.',
  '6. 본문에 없는 가격·순위·수치를 채워 넣지 않는다. 재료가 부족하면 카드 수를 줄인다.',
  '7. 본문을 못 가져온 후보는 근거를 "미확인"으로 적는다.',
  '8. 대상 독자나 편집 방향에 따라 결과가 크게 달라질 때만 되묻는다.',
  '',
  '되물어야 하면 (정말 갈릴 때만, 한 번):',
  '{"status":"need_input","question":"...","options":["...","..."],"why":"이 답에 따라 무엇이 달라지는지 한 줄"}',
  '',
  '만들 수 있으면:',
  '{"status":"result","storyboard":{"audience":"...","angle":"...","hooks":["...","..."],',
  '"items":[{"name":"본문에 있던 품목명 그대로","from":"c1","evidence":"confirmed|weak|retail_only|unconfirmed",',
  '"affiliate":true,"query_used":"실제로 쓴 검색어","sources":["url"]}],',
  '"cards":[{"no":1,"role":"표지","title":"...","body":"...","source":"확인한 URL 또는 미확인",',
  '"image_plan":"구도·분위기·색과 글자 넣을 빈 공간. 최종 문구는 그리지 않는다"}]}}',
  '',
  '규칙:',
  '- 카드는 5~8장. 표지는 관심을 끌고, 본문 카드는 하나의 핵심만, 마지막 카드는 요약 또는 다음 행동.',
  '- 근거 없는 순위·수치·과장 금지. 확인하지 못한 숫자는 아예 쓰지 마라.',
  '- 후킹 문구는 확인된 사실 범위 안에서만 쓴다.',
  '- source에는 실제로 확인한 URL을 넣는다. 확인하지 못했으면 "미확인"이라고 적는다.',
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

JS_APPROVE_FORM = r"""
const fs = require('fs');
const sb = $json.storyboard ?? {};
const cards = sb.cards ?? [];
if (!cards.length) throw new Error('스토리보드에 카드가 없습니다.');

// Park it on disk so the approval step reads back the exact version that was
// shown, instead of guessing which run of this node the loop landed on.
fs.writeFileSync($json.runDir + '/storyboard-latest.json', JSON.stringify(sb, null, 2), 'utf8');

const he = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;')
  .replace(/>/g, '&gt;').replace(/"/g, '&quot;');

const html = '<p><b>독자</b> ' + he(sb.audience) + '<br><b>앵글</b> ' + he(sb.angle) + '</p>'
  + ((sb.hooks ?? []).length
      ? '<p><b>후킹 문구 후보</b></p><ul>' + sb.hooks.map(h => '<li>' + he(h) + '</li>').join('') + '</ul>'
      : '')
  + ((sb.items ?? []).length
      ? '<p><b>품목 교차 확인</b></p><ul>' + sb.items.map(i =>
          '<li>' + he(i.name) + ' — <b>' + he(i.evidence) + '</b>'
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

return [{ json: { ...$json, formFields: JSON.stringify(fields).split('$').join('$$') } }];
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
  'confirmed = 서로 다른 블로그·기사 2곳 이상 / weak = 1곳 / retail_only = 쇼핑몰 페이지만 / unconfirmed = 못 찾음',
  '',
  '이미지는 아직 만들지 않았습니다. 이미지 출처와 생성 기록은 다음 단계에서 이 파일에 추가합니다.',
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


def form_page(name, json_output, pos, button):
    return node(name, 'n8n-nodes-base.form', 2.5, {
        'operation': 'page', 'defineForm': 'json', 'jsonOutput': json_output,
        'options': {'buttonLabel': button},
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
    code('후보 화면 만들기', JS_PICK_FORM, [1080, 0]),
    form_page('후보 선택', '={{ $json.formFields }}', [1300, 0], '이걸로 만들기'),
    code('선택 정리', JS_PICKED, [1520, 0]),

    # Fetch the sources ourselves. Asking the model to open these pages does
    # not work -- Naver and Instagram refuse the fetch, YouTube needs JS --
    # and both of these endpoints are covered by credentials we already have.
    node('유튜브 원문', 'n8n-nodes-base.httpRequest', 4.5, {
        'url': 'https://www.googleapis.com/youtube/v3/videos',
        'authentication': 'genericCredentialType', 'genericAuthType': 'httpQueryAuth',
        'sendQuery': True,
        'queryParameters': {'parameters': [
            {'name': 'part', 'value': 'snippet,statistics'},
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

    code('심층조사 지시', JS_DEEP, [2180, -110]),
    node('Claude: 심층조사', 'n8n-nodes-base.executeCommand', 1, {'command': cmd(session=True)}, [2400, -110]),
    code('응답 파싱', JS_PARSE, [2620, -110]),

    node('질문인가?', 'n8n-nodes-base.if', 2.3,
         {'conditions': cond_equals('={{ $json.status }}', 'need_input'), 'options': {}}, [2840, -110]),

    form_page('질문', JS_QUESTION_FORM, [3060, -300], '답변 제출'),
    code('답변 전달', JS_ANSWER, [3280, -300]),

    code('스토리보드 화면 만들기', JS_APPROVE_FORM, [3060, 60]),
    form_page('스토리보드 승인', '={{ $json.formFields }}', [3280, 60], '제출'),

    node('승인인가?', 'n8n-nodes-base.if', 2.3,
         {'conditions': cond_equals("={{ $json.decision ?? $json['진행 여부'] }}", '승인'),
          'options': {}}, [3500, 60]),

    code('저장', JS_SAVE, [3720, -40]),
    code('수정 지시', JS_REVISE, [3720, 200]),

    node('완료', 'n8n-nodes-base.form', 2.5, {
        'operation': 'completion', 'respondWith': 'text',
        'completionTitle': '카드뉴스 원고 완성',
        'completionMessage': "={{ '카드 ' + $json.cards + '장.\\n저장 위치: ' + $json.runDir"
                             " + '\\n파일: ' + $json.files }}",
        'options': {},
    }, [3940, -40], {'webhookId': 'cardnews-form-done'}),
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
    'Claude: 후보 평가': {'main': [m('후보 화면 만들기')]},
    '후보 화면 만들기': {'main': [m('후보 선택')]},
    '후보 선택': {'main': [m('선택 정리')]},
    '선택 정리': {'main': [m('유튜브 원문')]},
    '유튜브 원문': {'main': [m('웹 원문')]},
    '웹 원문': {'main': [m('심층조사 지시')]},
    '심층조사 지시': {'main': [m('Claude: 심층조사')]},
    'Claude: 심층조사': {'main': [m('응답 파싱')]},
    '응답 파싱': {'main': [m('질문인가?')]},
    '질문인가?': {'main': [m('질문'), m('스토리보드 화면 만들기')]},
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
