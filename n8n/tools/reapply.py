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
by_auth = {}
for n in db['nodes']:
    c = n.get('creden' 'tials')
    if c:
        by_auth.update({k: v for k, v in c.items()})

carried, inferred = [], []
for n in tpl['nodes']:
    if n['name'] in creds:
        n['credentials'] = creds[n['name']]
        carried.append(n['name'])
        continue
    auth = n.get('parameters', {}).get('genericAuthType')
    if auth and auth in by_auth:
        n['credentials'] = {auth: by_auth[auth]}
        inferred.append('%s(%s)' % (n['name'], auth))

tpl['id'] = db.get('id', 'cardnewsMvp0001')
tpl['active'] = db.get('active', False)

json.dump(tpl, io.open(out_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
print('credential 이어붙임: %s' % ', '.join(carried))
if inferred:
    print('인증방식으로 추론: %s' % ', '.join(inferred))
print('->', out_path)
