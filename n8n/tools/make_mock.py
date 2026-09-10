# -*- coding: utf-8 -*-
"""
Builds a fully-mocked copy of the card-news workflow that runs headlessly:
  - Form Trigger  -> Manual Trigger + a Code node emitting the submitted values
  - HTTP searches -> Code nodes emitting canned YouTube / Tavily payloads
  - Form pages    -> Code nodes that VALIDATE the generated formFields JSON
                     against n8n's own allowlists, then emit a canned submission

pinData is ignored by `n8n execute`, hence substitution rather than pinning.
"""
import json, io

SRC = 'C:/Users/jb660/Desktop/project_2/n8n/workflows/cardnews-mvp.json'
DST = 'C:/Users/jb660/Desktop/project_2/n8n/workflows/cardnews-mock.json'

wf = json.load(io.open(SRC, encoding='utf-8'))
wf['id'] = 'cardnewsMock001'
wf['name'] = '[모의] 카드뉴스 MVP 전 구간 점검'
wf['pinData'] = {}

# --------------------------------------------------------------- mock payloads

YT = {'kind': 'youtube#searchListResponse', 'items': [
    {'id': {'videoId': 'vid0000001'}, 'snippet': {
        'title': '오사카 여행 기념품 BEST 10 사와봤습니다',
        'description': '실제로 사온 기념품 전부 공개합니다. 가격도 같이 적어뒀어요',
        'channelTitle': '여행하는판다', 'publishedAt': '2026-09-04T10:00:00Z'}},
    {'id': {'videoId': 'vid0000002'}, 'snippet': {
        'title': '오사카 여행 기념품 BEST 10 사와봤어요',
        'description': '중복 묶기 확인용 — 제목이 거의 같은 영상',
        'channelTitle': '트래블러K', 'publishedAt': '2026-09-05T10:00:00Z'}},
    {'id': {'videoId': 'vid0000003'}, 'snippet': {
        'title': '유럽 여행 선물 하울 | 파리에서 사온 것들',
        'description': '파리 기념품샵 3곳 돌면서 산 것들 보여드려요',
        'channelTitle': '파리댁', 'publishedAt': '2026-09-06T10:00:00Z'}},
    {'id': {'videoId': 'vid0000004'}, 'snippet': {
        'title': '공항 면세점 선물 추천 5가지',
        'description': '면세점에서 뭐 살지 고민되면 보세요',
        'channelTitle': '면세점털이', 'publishedAt': '2026-09-07T10:00:00Z'}},
    {'id': {'videoId': 'vid0000005'}, 'snippet': {
        'title': '베트남 다낭 기념품 시장 털기',
        'description': '한시장에서 흥정하는 법까지',
        'channelTitle': '다낭러버', 'publishedAt': '2026-09-08T10:00:00Z'}},
]}

TAVILY = {'query': '여행 기념품 추천', 'results': [
    {'title': '여행 기념품 추천 <b>2026</b> 총정리',
     'url': 'https://example-blog.tistory.com/1?utm_source=x&si=abc',
     'content': '나라별로 실패 없는 기념품을 정리했습니다. 가격대와 부피까지 &quot;고려&quot;했어요. &amp; 항공 규정도 봅니다.',
     'published_date': '2026-09-05'},
    {'title': '캐리어에 넣기 좋은 선물 고르는 법',
     'url': 'https://example-blog.tistory.com/2',
     'content': '깨지기 쉬운 기념품은 이렇게 포장하세요.',
     'published_date': None},
    {'title': '기념품 값 $12에 산 것들 — $ 이스케이프 확인용',
     'url': 'https://youtu.be/vid0000001',
     'content': '달러 기호와 youtu.be 정규화를 동시에 확인하는 항목',
     'published_date': '2026-09-07'},
]}

# 실측(runs/_probe): 성공은 객체 하나로 오고 청크가 나뉘지 않았다. 오류는
# 배열 [{"error":...}] 로 왔다. 파서는 두 모양을 다 받게 해 뒀으므로 모의도
# 둘 다 태운다 — 성공은 객체 + 두 조각, 오류는 배열. 조각 나누기는 실측에서
# 안 나왔지만 스트리밍으로 바뀔 여지가 있어 경로를 살려 둔다.
_ANALYSIS = json.dumps({
    'summary': '오사카에서 사 온 기념품을 하나씩 꺼내 보여 주는 영상이다. 가격을 화면에 띄운다.',
    'items': [
        {'name': '코로로 젤리', 'at': '01:24', 'note': '화면에 "포도맛이 제일 인기" 라고 적혀 있음'},
        {'name': '오사카 한정 킷캣', 'at': '03:10', 'note': ''},
    ],
}, ensure_ascii=False)
_HALF = len(_ANALYSIS) // 2

GEMINI_OK = {
    'id': 'v1_mock', 'object': 'interaction', 'status': 'completed',
    'model': 'gemini-3.5-flash', 'service_tier': 'standard',
    'usage': {'total_tokens': 107139},
    'steps': [
        # 실측에서 사고 단계가 앞에 왔고 content 가 비어 있었다. model_output
        # 만 골라야 한다.
        {'type': 'thought', 'content': []},
        {'type': 'model_output', 'content': [{'type': 'text', 'text': _ANALYSIS[:_HALF]}]},
        {'type': 'model_output', 'content': [{'type': 'text', 'text': _ANALYSIS[_HALF:]}]},
    ],
}

GEMINI_ERR = [{'error': {'code': 429, 'message': 'Quota exceeded for youtube video seconds',
                         'status': 'RESOURCE_EXHAUSTED'}}]

FORM_INPUT = {
    'topic': '여행 기념품 추천',
    'period': '최근 7일',
    'purpose': '캐리어 플랫폼 인스타 계정 — 여행 준비하는 20~30대',
}

# ---------------------------------------------------- form-field validator (JS)

# Copied from the installed n8n's n8n-workflow/dist/cjs/type-validation.js so the
# mock fails here rather than in the browser.
VALIDATE = r"""
const ALLOWED_KEYS = ['fieldLabel','fieldType','placeholder','defaultValue','fieldOptions',
  'multiselect','multipleFiles','acceptFileTypes','formatDate','requiredField','fieldValue',
  'elementName','html','fieldName','limitSelection','numberOfSelections','minSelections','maxSelections'];
const ALLOWED_TYPES = ['date','dropdown','email','file','number','password','text','textarea',
  'checkbox','radio','html','hiddenField'];

const rawStr = String($json.formFields ?? '');
if (!rawStr) throw new Error('formFields 가 비어 있습니다.');

// n8n undoes the $$ escaping when it splices the value in, so undo it here too.
const fields = JSON.parse(rawStr.split('$$').join('$'));
if (!Array.isArray(fields)) throw new Error('formFields 가 배열이 아닙니다.');

fields.forEach((f, i) => {
  for (const k of Object.keys(f)) {
    if (!ALLOWED_KEYS.includes(k)) throw new Error('필드 ' + i + ' 의 키 "' + k + '" 는 허용되지 않습니다.');
  }
  if (f.fieldType && !ALLOWED_TYPES.includes(f.fieldType)) {
    throw new Error('필드 ' + i + ' 의 fieldType "' + f.fieldType + '" 는 허용되지 않습니다.');
  }
  if (f.fieldOptions) {
    const values = Array.isArray(f.fieldOptions) ? f.fieldOptions : f.fieldOptions.values;
    if (!Array.isArray(values)) throw new Error('필드 ' + i + ' 의 fieldOptions.values 가 배열이 아닙니다.');
    values.forEach((o, j) => {
      if (typeof o !== 'object' || o === null || Object.keys(o).length !== 1 || typeof o.option !== 'string') {
        throw new Error('필드 ' + i + ' 의 옵션 ' + j + ' 는 { option: "문자열" } 하나여야 합니다.');
      }
    });
  }
});
"""

MOCK_PICK = VALIDATE + r"""
// --- regression checks on 후보 정리 -------------------------------------
// The mock feeds 8 raw hits: 5 YouTube (two with near-identical titles) and
// 3 web (one of them a youtu.be link to an already-listed video, one carrying
// utm_source & si). Expect 8 -> 6: one dropped by URL, one merged by title.
const cands = $json.candidates ?? [];
const dirty = cands.filter(c => /utm_|[?&]si=|youtu\.be/i.test(c.url));
if (dirty.length) throw new Error('URL 정규화 실패: ' + dirty.map(c => c.url).join(', '));
if (cands.length !== 6) {
  throw new Error('중복 묶기 결과가 6개가 아닙니다: ' + cands.length
    + ' — ' + cands.map(c => c.id + '(dup' + c.duplicates + ')').join(' '));
}
console.log('[모의] 후보 정리 OK: 8건 -> ' + cands.length + '건, '
  + cands.map(c => c.id + ':dup' + c.duplicates).join(' '));

const cb = fields.find(f => f.fieldType === 'checkbox');
if (!cb) throw new Error('체크박스 필드가 없습니다.');
const opts = (cb.fieldOptions.values ?? cb.fieldOptions).map(o => o.option);
if (opts.length < 2) throw new Error('후보 옵션이 2개 미만입니다: ' + opts.length);

// 영상 후보 2개를 고른다. 그냥 앞 2개를 고르면 라운드로빈 순서 때문에
// 유튜브 1 + 웹 1 이 되어 Gemini 호출이 1건뿐이고, 모의 응답의 오류 경로가
// 안 돈다. 아이디로 골라야 옵션 텍스트 형식에 의존하지 않는다.
const vidIds = cands.filter(c => /[?&]v=|youtu\.be\//.test(c.url)).map(c => c.id);
if (vidIds.length < 2) throw new Error('영상 후보가 2개 미만입니다: ' + vidIds.length);
const picks = vidIds.slice(0, 2).map(id => {
  const o = opts.find(t => t.endsWith('— ' + id) || t.endsWith('' + id));
  if (!o) throw new Error('후보 ' + id + ' 에 해당하는 옵션을 못 찾았습니다.');
  return o;
});
console.log('[모의] 후보 옵션 ' + opts.length + '개, 영상 2개 선택: ' + picks.join(' | '));
return [{ json: { picks } }];
"""

MOCK_QUESTION = r"""
// The question page builds its fields inline, so validate what the branch produced.
if (!$json.question) throw new Error('질문이 비어 있습니다.');
const opts = $json.options ?? [];
console.log('[모의] 질문: ' + $json.question + ' / 선택지: ' + JSON.stringify(opts));
return [{ json: { answer: String(opts[0] ?? '일반 사용자'), answerFree: '' } }];
"""

MOCK_APPROVE = VALIDATE + r"""
const radio = fields.find(f => f.fieldName === 'decision');
if (!radio) throw new Error('진행 여부 radio 필드가 없습니다.');
const html = fields.find(f => f.fieldType === 'html');
if (!html || !html.html) throw new Error('스토리보드 미리보기 html 이 없습니다.');
// 영상 분석이 원문에 실제로 접혔는지. 이게 깨지면 Gemini 응답 파싱이 틀린 것이고,
// 원문 대조가 화면에서 본 품목을 not_in_source 로 잘못 찍는다.
const fs = require('fs');
const runDir = $('선택 정리').first().json.runDir;
const sf = JSON.parse(fs.readFileSync(runDir + '/sources-fetched.json', 'utf8'));
if (!(sf.watched ?? []).length) {
  throw new Error('영상 분석이 하나도 접히지 않았습니다: ' + JSON.stringify(sf.videoErrors));
}
if (!(sf.videoErrors ?? []).length) throw new Error('오류 경로를 안 탔습니다 — 모의 응답을 확인하세요.');
const st = fs.readFileSync(runDir + '/source-text.txt', 'utf8');
if (!st.includes('영상 분석 (Gemini')) throw new Error('source-text.txt 에 영상 분석이 없습니다.');
if (!st.includes('코로로 젤리 [01:24]')) throw new Error('영상 분석 품목·시각이 원문에 없습니다.');
console.log('[모의] 영상 분석 접힘 ' + sf.watched.length + '건 / 오류 ' + sf.videoErrors.length + '건');

console.log('[모의] 스토리보드 미리보기 ' + html.html.length + '자, 승인 제출');
return [{ json: { decision: '승인', revision: '' } }];
"""


def code_node(name, js, pos):
    return {'parameters': {'jsCode': js.strip()}, 'type': 'n8n-nodes-base.code',
            'typeVersion': 2, 'position': pos,
            'id': 'mock0000-0000-4000-8000-%012d' % (abs(hash(name)) % 10 ** 12),
            'name': name}


by_name = {n['name']: n for n in wf['nodes']}

# 1. trigger
wf['nodes'] = [n for n in wf['nodes'] if n['name'] != '카드뉴스 시작']
wf['connections'].pop('카드뉴스 시작', None)
wf['nodes'].insert(0, {'parameters': {}, 'type': 'n8n-nodes-base.manualTrigger',
                       'typeVersion': 1, 'position': [-460, 0],
                       'id': 'mock0000-0000-4000-8000-000000000001', 'name': '[모의] 시작'})
wf['nodes'].insert(1, code_node('[모의] 폼 입력',
                                'return [{ json: %s }];' % json.dumps(FORM_INPUT, ensure_ascii=False),
                                [-240, 0]))
wf['connections']['[모의] 시작'] = {'main': [[{'node': '[모의] 폼 입력', 'type': 'main', 'index': 0}]]}
wf['connections']['[모의] 폼 입력'] = {'main': [[{'node': '준비', 'type': 'main', 'index': 0}]]}

# 2. searches -> canned payloads (keeps node names, so connections stay valid)
for name, payload in (('유튜브 검색', YT), ('웹 검색', TAVILY)):
    n = by_name[name]
    n['type'] = 'n8n-nodes-base.code'
    n['typeVersion'] = 2
    n['parameters'] = {'jsCode': 'return [{ json: %s }];' % json.dumps(payload, ensure_ascii=False)}
    n.pop('onError', None)
    n.pop('credentials', None)

# 2b. Gemini -> canned response. Stubbed so the mock never posts to Google,
#     and so the steps[] parsing in 심층조사 지시 is actually exercised.
g = by_name['제미나이 영상 분석']
g['type'] = 'n8n-nodes-base.code'
g['typeVersion'] = 2
g['parameters'] = {'jsCode': chr(10).join([
    # HTTP 노드가 responseFormat=text 라 {data: '<원문>'} 로 나온다.
    'const canned = %s;' % json.dumps(
        [{'data': json.dumps(x, ensure_ascii=False)} for x in (GEMINI_OK, GEMINI_ERR)],
        ensure_ascii=False),
    '// 입력 아이템 수만큼 내보내야 심층조사 지시의 인덱스 짝이 유지된다.',
    'return $input.all().map((_, i) => ({ json: canned[i %  canned.length] }));'.replace('%  ', '% '),
])}
g.pop('onError', None)
g.pop('retryOnFail', None)
g.pop('credentials', None)

# 3. form pages -> validator + canned submission
for name, js in (('후보 선택', MOCK_PICK), ('질문', MOCK_QUESTION), ('스토리보드 승인', MOCK_APPROVE)):
    n = by_name[name]
    n['type'] = 'n8n-nodes-base.code'
    n['typeVersion'] = 2
    n['parameters'] = {'jsCode': js.strip()}
    n.pop('webhookId', None)

# 4. completion page -> plain code so the run finishes instead of responding
done = by_name['완료']
done['type'] = 'n8n-nodes-base.code'
done['typeVersion'] = 2
done['parameters'] = {'jsCode': "console.log('[모의] 완료: ' + JSON.stringify($json)); return $input.all();"}
done.pop('webhookId', None)

json.dump(wf, io.open(DST, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
print('wrote %s (%d nodes)' % (DST, len(wf['nodes'])))
