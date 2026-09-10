# -*- coding: utf-8 -*-
"""
Turns the DB copy of cardnewsMvp0001 (which carries the credentials the user
wired in the UI) into a headlessly runnable variant:

  Form Trigger -> Manual Trigger + a Code node emitting the submitted values
  Form pages   -> Code nodes that validate the generated formFields JSON,
                  then emit a canned submission

The two HTTP search nodes are left ALONE, so this hits the real YouTube and
Tavily APIs. That is the point: everything so far was mock data.

Usage: python make_live.py <exported.json>
"""
import json, io, sys

SRC = sys.argv[1]
DST = 'C:/Users/jb660/Desktop/project_2/n8n/runs/_check/cardnews-live.json'

data = json.load(io.open(SRC, encoding='utf-8'))
wf = data[0] if isinstance(data, list) else data
wf['id'] = 'cardnewsLive001'
wf['name'] = '[실키] 카드뉴스 첫 실행 점검'
wf['active'] = False
wf['pinData'] = {}

FORM_INPUT = {
    'topic': '오사카 기념품 추천',
    'period': '최근 30일',
    'purpose': '인스타 릴스 — 오사카 처음 가는 20~30대',
}

VALIDATE = r"""
const ALLOWED_KEYS = ['fieldLabel','fieldType','placeholder','defaultValue','fieldOptions',
  'multiselect','multipleFiles','acceptFileTypes','formatDate','requiredField','fieldValue',
  'elementName','html','fieldName','limitSelection','numberOfSelections','minSelections','maxSelections'];
const ALLOWED_TYPES = ['date','dropdown','email','file','number','password','text','textarea',
  'checkbox','radio','html','hiddenField'];

const rawStr = String($json.formFields ?? '');
if (!rawStr) throw new Error('formFields 가 비어 있습니다.');
const fields = JSON.parse(rawStr.split('$$').join('$'));
if (!Array.isArray(fields)) throw new Error('formFields 가 배열이 아닙니다.');
fields.forEach((f, i) => {
  for (const k of Object.keys(f)) {
    if (!ALLOWED_KEYS.includes(k)) throw new Error('필드 ' + i + ' 키 "' + k + '" 불가');
  }
  if (f.fieldType && !ALLOWED_TYPES.includes(f.fieldType)) {
    throw new Error('필드 ' + i + ' fieldType "' + f.fieldType + '" 불가');
  }
  if (f.fieldOptions) {
    const values = Array.isArray(f.fieldOptions) ? f.fieldOptions : f.fieldOptions.values;
    if (!Array.isArray(values)) throw new Error('필드 ' + i + ' fieldOptions.values 불량');
    values.forEach((o, j) => {
      if (typeof o !== 'object' || o === null || Object.keys(o).length !== 1 || typeof o.option !== 'string') {
        throw new Error('필드 ' + i + ' 옵션 ' + j + ' 는 { option: 문자열 } 하나여야 함');
      }
    });
  }
});
"""

# Real-data checks. These are the assertions that could not run on mock data.
LIVE_PICK = VALIDATE + r"""
const fs = require('fs');
const cands = $json.candidates ?? [];
const errs = $json.sourceErrors ?? [];

// Dump everything so the run can be inspected afterwards even if it throws.
fs.writeFileSync($json.runDir + '/LIVE-REPORT.json', JSON.stringify({
  sourceErrors: errs,
  bySource: cands.reduce((a, c) => (a[c.source] = (a[c.source] || 0) + 1, a), {}),
  withDate: cands.filter(c => c.publishedAt).length,
  withValue: cands.filter(c => c.value).length,
  candidates: cands,
}, null, 2), 'utf8');

if (errs.length) console.log('소스 상태: ' + errs.join(' / '));
if (cands.length < 5) throw new Error('후보가 ' + cands.length + '개뿐입니다.');

const bySource = cands.reduce((a, c) => (a[c.source] = (a[c.source] || 0) + 1, a), {});
// The 12-item cap must not wipe out a source that actually returned hits.
if (!errs.length && Object.keys(bySource).length < 2) {
  throw new Error('소스가 ' + JSON.stringify(bySource) + ' 하나뿐입니다. 오류는 없었으니 상한에서 잘린 것입니다.');
}
// Tavily answers 200 with an empty list at random, so an empty web source is
// a warning, not a failure. Only both being empty means something is broken.
if (!bySource['유튜브'] && !bySource['웹']) throw new Error('두 소스 모두 0개입니다.');
if (!bySource['유튜브']) console.log('경고: 유튜브 0건 — 키/쿼터 확인');
if (!bySource['웹']) console.log('경고: 웹 0건 — Tavily 간헐적 빈 응답');

const noValue = cands.filter(c => !c.value).length;
if (noValue) throw new Error('Claude 평가가 안 붙은 후보 ' + noValue + '개 (id 매칭 실패 의심)');

const cb = fields.find(f => f.fieldType === 'checkbox');
const opts = (cb.fieldOptions.values ?? cb.fieldOptions).map(o => o.option);
return [{ json: { picks: opts.slice(0, 2) } }];
"""

LIVE_QUESTION = r"""
if (!$json.question) throw new Error('질문이 비어 있습니다.');
const opts = $json.options ?? [];
return [{ json: { answer: String(opts[0] ?? '일반 사용자'), answerFree: '' } }];
"""

LIVE_APPROVE = VALIDATE + r"""
const radio = fields.find(f => f.fieldName === 'decision');
if (!radio) throw new Error('진행 여부 radio 필드가 없습니다.');
const html = fields.find(f => f.fieldType === 'html');
if (!html || !html.html) throw new Error('스토리보드 미리보기 html 이 없습니다.');
return [{ json: { decision: '승인', revision: '' } }];
"""

by_name = {n['name']: n for n in wf['nodes']}

# trigger
wf['nodes'] = [n for n in wf['nodes'] if n['name'] != '카드뉴스 시작']
wf['connections'].pop('카드뉴스 시작', None)
wf['nodes'].insert(0, {'parameters': {}, 'type': 'n8n-nodes-base.manualTrigger',
                       'typeVersion': 1, 'position': [-460, 0],
                       'id': 'live0000-0000-4000-8000-000000000001', 'name': '[실키] 시작'})
wf['nodes'].insert(1, {'parameters': {'jsCode': 'return [{ json: %s }];'
                                      % json.dumps(FORM_INPUT, ensure_ascii=False)},
                       'type': 'n8n-nodes-base.code', 'typeVersion': 2, 'position': [-240, 0],
                       'id': 'live0000-0000-4000-8000-000000000002', 'name': '[실키] 폼 입력'})
wf['connections']['[실키] 시작'] = {'main': [[{'node': '[실키] 폼 입력', 'type': 'main', 'index': 0}]]}
wf['connections']['[실키] 폼 입력'] = {'main': [[{'node': '준비', 'type': 'main', 'index': 0}]]}

# form pages -> validator + canned submission.  HTTP nodes untouched.
for name, js in (('후보 선택', LIVE_PICK), ('질문', LIVE_QUESTION), ('스토리보드 승인', LIVE_APPROVE)):
    n = by_name[name]
    n['type'] = 'n8n-nodes-base.code'
    n['typeVersion'] = 2
    n['parameters'] = {'jsCode': js.strip()}
    n.pop('webhookId', None)

done = by_name['완료']
done['type'] = 'n8n-nodes-base.code'
done['typeVersion'] = 2
done['parameters'] = {'jsCode': 'return $input.all();'}
done.pop('webhookId', None)

json.dump(wf, io.open(DST, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
http = [n['name'] + ('(cred ok)' if n.get('credentials') else '(NO CRED)')
        for n in wf['nodes'] if n['type'].endswith('httpRequest')]
print('wrote %s (%d nodes) | http: %s' % (DST, len(wf['nodes']), ', '.join(http)))
