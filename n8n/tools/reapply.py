# -*- coding: utf-8 -*-
"""
Re-imports the freshly built template into n8n WITHOUT losing the credentials
the user wired in the UI. Credentials live only in the DB copy, so carry them
across by node name.

Usage: python reapply.py <db-export.json> <out.json>
"""
import json, io, sys
from urllib.parse import urlparse

TEMPLATE = 'C:/Users/jb660/Desktop/project_2/n8n/workflows/cardnews-mvp.json'
db_path, out_path = sys.argv[1], sys.argv[2]

tpl = json.load(io.open(TEMPLATE, encoding='utf-8'))
db = json.load(io.open(db_path, encoding='utf-8'))
db = db[0] if isinstance(db, list) else db

creds = {n['name']: n['creden' 'tials'] for n in db['nodes'] if n.get('credentials')}
if not creds:
    sys.exit('DB 사본에 credential이 없습니다. UI에서 연결했는지 확인하세요.')

# Infer a credential for a NEW http node so the user does not have to wire it
# in the UI again -- but match on the HOST, not just the auth type.
#
# Auth type alone is not enough. Tavily and Gemini are BOTH Header Auth, and
# with only Tavily wired the "exactly one candidate" rule would have attached
# it to the Gemini node, posting `Authorization: Bearer tvly-...` to
# generativelanguage.googleapis.com -- our key handed to a third party, not
# just a 401. A credential belongs to a SERVICE, and the host names it.
def host_of(n):
    u = str(n.get('parameters', {}).get('url', ''))
    if '://' not in u:
        u = 'https://' + u
    return urlparse(u).hostname or ''


by_host = {}
for n in db['nodes']:
    for k, v in (n.get('creden' 'tials') or {}).items():
        by_host.setdefault((k, host_of(n)), v)

carried, inferred, unwired = [], [], []
for n in tpl['nodes']:
    if n['name'] in creds:
        n['credentials'] = creds[n['name']]
        carried.append(n['name'])
        continue
    auth = n.get('parameters', {}).get('genericAuthType')
    if not auth:
        continue
    v = by_host.get((auth, host_of(n)))
    if v:
        n['credentials'] = {auth: v}
        inferred.append('%s(%s)' % (n['name'], host_of(n)))
    else:
        # 틀린 키를 붙이느니 비워 둔다. 엉뚱한 서비스로 키가 나간다.
        unwired.append('%s -> %s (%s)' % (n['name'], host_of(n) or '?', auth))

tpl['id'] = db.get('id', 'cardnewsMvp0001')
tpl['active'] = db.get('active', False)

json.dump(tpl, io.open(out_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
print('credential 이어붙임: %s' % ', '.join(carried))
if inferred:
    print('같은 호스트라 추론: %s' % ', '.join(inferred))
if unwired:
    print('')
    print('[!] credential 이 비어 있는 노드가 있습니다. 이 호스트에 쓰는 키를')
    print('    아직 연결한 적이 없어서 추측하지 않았습니다.')
    for a in unwired:
        print('    %s' % a)
    print('    n8n UI 에서 해당 노드를 열어 직접 골라 주세요.')
print('->', out_path)
