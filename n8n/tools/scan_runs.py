# -*- coding: utf-8 -*-
"""모든 실행 폴더를 훑어 평가용 표를 낸다.

기억이 아니라 실제 산출물에서 뽑는다. 기능이 언제 들어왔는지도 산출물의
유무로 드러난다 — items-checked.json 이 없으면 원문 대조 도입 전이다.

사용법:
    python tools/scan_runs.py            표
    python tools/scan_runs.py --csv      쉼표 구분 (표 문서에 붙일 때)
"""
import io
import json
import os
import sys
import glob
import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNS = os.path.join(ROOT, 'runs')


def workflow_of(ids):
    """실행번호 -> 워크플로 id. 모의와 실키를 섞으면 숫자가 거짓말을 한다.
    모의는 credential 이 없어 원문 확보가 늘 실패하므로, 합치면 확보율이
    실제보다 낮게 나온다."""
    import sqlite3
    db = os.path.join(os.environ.get('USERPROFILE', ''), '.n8n', 'database.sqlite')
    out = {}
    if not os.path.exists(db):
        return out
    try:
        c = sqlite3.connect('file:' + db.replace(os.sep, '/') + '?mode=ro', uri=True, timeout=10)
        for eid, wid in c.execute('select id, workflowId from execution_entity'):
            out[str(eid)] = wid
        c.close()
    except Exception:
        pass
    return out


def jload(path):
    try:
        return json.load(io.open(path, encoding='utf-8'))
    except Exception:
        return None


def scan(d):
    """실행 폴더 하나에서 뽑을 수 있는 것만 뽑는다. 없는 건 None."""
    rid = os.path.basename(d)
    r = {'run': rid, 'topic': None, 'when': None,
         'cands': None, 'yt': None, 'web': None,
         'verified': None, 'total': None, 'watched': None,
         'items': None, 'cards': None,
         'ev': {}, 'vd': {}, 'done': False, 'shots': None}

    # 언제 — 폴더의 첫 파일 시각
    files = glob.glob(os.path.join(d, '*'))
    if files:
        r['when'] = datetime.datetime.fromtimestamp(
            min(os.path.getmtime(f) for f in files)).strftime('%m-%d %H:%M')

    cands = jload(os.path.join(d, 'candidates-raw.json'))
    if isinstance(cands, list):
        r['cands'] = len(cands)
        r['yt'] = sum(1 for c in cands if c.get('source') == '유튜브')
        r['web'] = r['cands'] - r['yt']

    sf = jload(os.path.join(d, 'sources-fetched.json'))
    if sf:
        r['verified'] = sf.get('verified')
        r['total'] = sf.get('total')
        # watched 는 영상 분석 도입 뒤에만 있다
        r['watched'] = len(sf.get('watched') or []) if 'watched' in sf else None

    chk = jload(os.path.join(d, 'items-checked.json'))
    if isinstance(chk, list):
        r['items'] = len(chk)
        for c in chk:
            r['ev'][c.get('evidence', '?')] = r['ev'].get(c.get('evidence', '?'), 0) + 1
            r['vd'][c.get('verdict', '?')] = r['vd'].get(c.get('verdict', '?'), 0) + 1

    sb = jload(os.path.join(d, 'storyboard.json')) or \
         jload(os.path.join(d, 'storyboard-latest.json'))
    if sb:
        r['cards'] = len(sb.get('cards') or [])
        if r['items'] is None:
            r['items'] = len(sb.get('items') or [])

    shots = jload(os.path.join(d, 'product-shots.json'))
    if isinstance(shots, list):
        r['shots'] = sum(len(s.get('images') or []) for s in shots)

    # 주제는 프롬프트에서 되읽는다. 따로 저장하는 파일이 없다.
    p1 = os.path.join(d, 'prompt-1.txt')
    if os.path.exists(p1):
        for line in io.open(p1, encoding='utf-8'):
            if '주제로 최근' in line:
                a = line.find('"')
                b = line.find('"', a + 1)
                if a > 0 and b > a:
                    r['topic'] = line[a + 1:b]
                break

    # 끝까지 갔는가 = 저장 노드가 원고를 냈는가
    r['done'] = os.path.exists(os.path.join(d, 'script.md'))
    return r


def main():
    dirs = sorted((d for d in glob.glob(os.path.join(RUNS, '*'))
                   if os.path.isdir(d) and os.path.basename(d).isdigit()),
                  key=lambda d: int(os.path.basename(d)))
    wf = workflow_of(None)
    rows = [scan(d) for d in dirs]
    for r in rows:
        w = wf.get(r['run'], '')
        r['kind'] = '실키' if w == 'cardnewsMvp0001' else ('모의' if w else '?')
    rows = [r for r in rows if r['cands'] is not None]   # 시작도 못 한 것은 뺀다

    only = None
    for a in sys.argv[1:]:
        if a in ('--real', '--mock'):
            only = '실키' if a == '--real' else '모의'
    if only:
        rows = [r for r in rows if r['kind'] == only]

    if '--csv' in sys.argv:
        print('run,kind,when,topic,cands,yt,web,verified,total,watched,items,cards,shots,done')
        for r in rows:
            print(','.join(str(x if x is not None else '') for x in [
                r['run'], r['kind'], r['when'], (r['topic'] or '').replace(',', ' '),
                r['cands'], r['yt'], r['web'], r['verified'], r['total'],
                r['watched'], r['items'], r['cards'], r['shots'],
                'Y' if r['done'] else 'N']))
        return 0

    print('%-4s %-4s %-11s %-20s %5s %7s %6s %5s %5s %5s %4s' % (
        '실행', '종류', '시각', '주제', '후보', '유튜브/웹', '원문', '영상', '품목', '카드', '완주'))
    print('-' * 98)
    for r in rows:
        print('%-4s %-4s %-11s %-20s %5s %7s %6s %5s %5s %5s %4s' % (
            r['run'], r['kind'], r['when'] or '', (r['topic'] or '')[:20],
            r['cands'] if r['cands'] is not None else '',
            '%s/%s' % (r['yt'], r['web']) if r['yt'] is not None else '',
            '%s/%s' % (r['verified'], r['total']) if r['verified'] is not None else '',
            r['watched'] if r['watched'] is not None else '-',
            r['items'] if r['items'] is not None else '',
            r['cards'] if r['cards'] is not None else '',
            'O' if r['done'] else 'X'))

    done = [r for r in rows if r['done']]
    print('-' * 98)
    real = [r for r in rows if r['kind'] == '실키']
    rdone = [r for r in real if r['done']]
    print('전체 %d건 · 완주 %d건 (%.0f%%)   |   실키 %d건 · 완주 %d건 (%.0f%%)' % (
        len(rows), len(done), 100.0 * len(done) / len(rows) if rows else 0,
        len(real), len(rdone), 100.0 * len(rdone) / len(real) if real else 0))

    # 근거 등급과 원문 대조 분포 — 완주한 것만
    ev, vd = {}, {}
    for r in done:
        for k, v in r['ev'].items():
            ev[k] = ev.get(k, 0) + v
        for k, v in r['vd'].items():
            vd[k] = vd.get(k, 0) + v
    if ev:
        print('근거 등급 : ' + ' · '.join('%s %d' % (k, v)
                                       for k, v in sorted(ev.items(), key=lambda x: -x[1])))
    if vd:
        print('원문 대조 : ' + ' · '.join('%s %d' % (k, v)
                                       for k, v in sorted(vd.items(), key=lambda x: -x[1])))

    # 영상 분석 도입 전후
    pre = [r for r in done if r['watched'] is None and r['verified'] is not None]
    post = [r for r in done if r['watched'] is not None]
    def rate(rs):
        t = sum(r['total'] or 0 for r in rs)
        v = sum(r['verified'] or 0 for r in rs)
        return (100.0 * v / t) if t else 0, v, t
    if pre and post:
        a, av, at = rate(pre)
        b, bv, bt = rate(post)
        print('원문 확보율: 영상분석 전 %.0f%% (%d/%d, %d건) → 후 %.0f%% (%d/%d, %d건)'
              % (a, av, at, len(pre), b, bv, bt, len(post)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
