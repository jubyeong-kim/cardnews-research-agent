# -*- coding: utf-8 -*-
"""실행이 중간에 끊겼을 때 디스크에 남은 것으로 원고를 복구한다.

승인 화면까지 갔으면 storyboard-latest.json 이 이미 디스크에 있다. 그 뒤에
n8n 이 죽거나 수정 루프가 실패해도 카드 내용은 살아 있다는 뜻이다. 이 스크립트는
저장 노드가 하던 일(script.md / sources.md / storyboard.json)을 그대로 한다.

저장 노드와 형식을 맞춰야 하므로 build_wf.py 의 JS_SAVE 를 고치면 여기도 같이
고칠 것. 두 벌이 되는 게 마음에 들지 않지만, 복구는 n8n 없이 돌아야 한다.

사용법: python tools/recover_run.py 50
"""
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
run_id = sys.argv[1] if len(sys.argv) > 1 else sys.exit('실행 번호를 주세요: python tools/recover_run.py 50')
d = os.path.join(ROOT, 'runs', run_id)
if not os.path.isdir(d):
    sys.exit('없는 실행입니다: ' + d)


def load(name, default=None):
    try:
        return json.load(io.open(os.path.join(d, name), encoding='utf-8'))
    except Exception:
        return default


sb = load('storyboard-latest.json')
if not sb:
    sys.exit('storyboard-latest.json 이 없습니다. 승인 화면까지 못 간 실행입니다.')

item_checks = load('items-checked.json', [])
chosen = load('selection.json', [])
cards = sb.get('cards', [])

# 주제·조사기준은 별도 파일에 없어서 프롬프트에서 되읽는다.
topic, researched_at, days = '(알 수 없음)', '(알 수 없음)', '?'
try:
    head = io.open(os.path.join(d, 'prompt-2.txt'), encoding='utf-8').read()[:900]
    m = re.search(r'^주제: (.+)$', head, re.M)
    if m:
        topic = m.group(1).strip()
    m = re.search(r'^조사 기준: (.+?) 기준 최근 (\d+)일', head, re.M)
    if m:
        researched_at, days = m.group(1).strip(), m.group(2)
except Exception:
    pass

VERDICT = {
    'in_source': '원문에 있음',
    'head_only': '괄호 앞만 원문에 있음 (괄호 안은 모델 추측 가능성)',
    'parts_in_source': '단어는 전부 원문에 있으나 이 이름 그대로는 없음 (모델이 조합)',
    'not_in_source': '원문에 없음',
    'no_source': '원문을 못 가져와 대조 불가',
}

script = ['# ' + topic, '',
          '- 독자: ' + sb.get('audience', ''),
          '- 앵글: ' + sb.get('angle', ''),
          '- 조사 기준: %s 기준 최근 %s일' % (researched_at, days),
          '- **중단된 실행을 디스크에서 복구한 것입니다** (tools/recover_run.py)',
          '']
for c in cards:
    script += ['## %s. [%s] %s' % (c.get('no'), c.get('role'), c.get('title')), '',
               str(c.get('body', '')), '',
               '- 근거: ' + str(c.get('source', '')),
               '- 그림 계획: ' + str(c.get('image_plan', '')), '']

sources = ['# 출처', '',
           '조사 기준: %s 기준 최근 %s일' % (researched_at, days), '',
           '## 선택한 후보', '']
for c in chosen:
    sources.append('- [%s](%s) — %s%s · %s' % (
        c.get('title', ''), c.get('url', ''), c.get('source', ''),
        ' · ' + c['channel'] if c.get('channel') else '',
        c.get('publishedAt') or '날짜 미확인'))
sources += ['', '## 카드별 근거', '']
sources += ['- %s. %s' % (c.get('no'), c.get('source', '')) for c in cards]
sources += ['', '## 품목 교차 확인', '']
items = sb.get('items', [])
if items:
    for i in items:
        line = '- %s — %s%s%s' % (
            i.get('name', ''), i.get('evidence', ''),
            ' · 제휴/광고 콘텐츠 출처' if i.get('affiliate') else '',
            ' · 검색어: ' + i['query_used'] if i.get('query_used') else '')
        for u in i.get('sources', []):
            line += '\n  - ' + u
        sources.append(line)
else:
    sources.append('(품목 추출 없음)')
sources += ['', '## 원문 대조', '']
sources += ['- %s — %s' % (v.get('name', ''), VERDICT.get(v.get('verdict'), '이름 없음'))
            for v in item_checks] or ['(대조 없음)']

io.open(os.path.join(d, 'storyboard.json'), 'w', encoding='utf-8').write(
    json.dumps(sb, ensure_ascii=False, indent=2))
io.open(os.path.join(d, 'script.md'), 'w', encoding='utf-8').write('\n'.join(script))
io.open(os.path.join(d, 'sources.md'), 'w', encoding='utf-8').write('\n'.join(sources))
print('복구 완료: runs/%s/ 에 storyboard.json, script.md, sources.md (카드 %d장, 품목 %d개)'
      % (run_id, len(cards), len(items)))
