# -*- coding: utf-8 -*-
"""
Re-imports the freshly built template into n8n WITHOUT losing the credentials
the user wired in the UI. Credentials live only in the DB copy, so carry them
across by node name.

Usage: python reapply.py <db-export.json> <out.json>
"""
import json, io, sys

TEMPLATE = 'C:/Users/jb660/Desktop/project_2/n8n/workflows/cardnews-mvp.json'
db_path, out_path = sys.argv[1], sys.argv[2]

tpl = json.load(io.open(TEMPLATE, encoding='utf-8'))
db = json.load(io.open(db_path, encoding='utf-8'))
db = db[0] if isinstance(db, list) else db

creds = {n['name']: n['creden' 'tials'] for n in db['nodes'] if n.get('credentials')}
if not creds:
    sys.exit('DB 사본에 credential이 없습니다. UI에서 연결했는지 확인하세요.')

# Also index by generic auth type, so a NEW http node picks up the right
# credential without the user having to wire it in the UI again.
#
# Only when the answer is unambiguous. Tavily and Gemini are BOTH Header Auth,
# so guessing here would have posted the Tavily key to generativelanguage.
# googleapis.com -- a wrong key leaking to a third party, not just a 401.
by_auth = {}
for n in db['nodes']:
    for k, v in (n.get('creden' 'tials') or {}).items():
        by_auth.setdefault(k, {})[v.get('id') or v.get('name')] = v

carried, inferred, ambiguous = [], [], []
for n in tpl['nodes']:
    if n['name'] in creds:
        n['credentials'] = creds[n['name']]
        carried.append(n['name'])
        continue
    auth = n.get('parameters', {}).get('genericAuthType')
    if not auth:
        continue
    opts = by_auth.get(auth, {})
    if len(opts) == 1:
        n['credentials'] = {auth: list(opts.values())[0]}
        inferred.append('%s(%s)' % (n['name'], auth))
    elif len(opts) > 1:
        ambiguous.append('%s(%s: %s)' % (
            n['name'], auth, ', '.join(sorted(v.get('name', '?') for v in opts.values()))))

tpl['id'] = db.get('id', 'cardnewsMvp0001')
tpl['active'] = db.get('active', False)

json.dump(tpl, io.open(out_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
print('credential 이어붙임: %s' % ', '.join(carried))
if inferred:
    print('인증방식으로 추론: %s' % ', '.join(inferred))
if ambiguous:
    # 틀린 키를 붙이느니 비워 두는 편이 낫다. 엉뚱한 서비스로 키가 나간다.
    print('')
    print('[!] 같은 인증방식 credential 이 여럿이라 추측하지 않았습니다.')
    for a in ambiguous:
        print('    %s' % a)
    print('    n8n UI 에서 해당 노드에 직접 골라 주세요.')
print('->', out_path)
