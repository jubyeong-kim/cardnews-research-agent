# -*- coding: utf-8 -*-
"""실행 하나의 단계별 소요·토큰·비용을 표로 낸다.

워크플로는 `runs/<실행번호>/metrics.jsonl` 에 단계마다 한 줄씩만 쌓는다.
집계는 여기서 한다 — 노드 안에서 집계하면 같은 계산이 노드마다 복사된다.

사용법:
    python tools/metrics.py 53          한 실행
    python tools/metrics.py 53 --json   metrics.json 으로도 저장
    python tools/metrics.py --all       전부 한 줄씩 (평가 표용)
"""
import io
import json
import os
import sys
import glob

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNS = os.path.join(ROOT, 'runs')

# 사람이 기다리는 구간. 이 시간은 워크플로 탓이 아니므로 합계에서 뺀다.
# 빼지 않으면 "20분 걸림" 이 사람이 커피 마신 시간인지 모델이 느린 건지 모른다.
HUMAN = ('후보선택(사람)',)


def load(run_id):
    p = os.path.join(RUNS, str(run_id), 'metrics.jsonl')
    if not os.path.exists(p):
        return []
    out = []
    for line in io.open(p, encoding='utf-8'):
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except ValueError:
                pass          # 반쯤 쓰다 죽은 줄은 버린다
    return sorted(out, key=lambda r: r.get('at', 0))


def summarize(run_id):
    """단계 목록 + 합계. 기록이 없으면 None."""
    rows = load(run_id)
    if not rows:
        return None

    steps = []
    for i, r in enumerate(rows):
        # 한 단계의 소요 = 그 단계가 찍힌 시각 - 직전 단계가 찍힌 시각.
        # 첫 줄('시작')은 앞이 없으므로 0 이다.
        ms = 0 if i == 0 else r['at'] - rows[i - 1]['at']
        steps.append({
            'stage': r.get('stage', '?'),
            'ms': ms,
            'human': r.get('stage') in HUMAN,
            'tool': r.get('tool'),
            'costUsd': float(r.get('costUsd') or 0),
            'tokens': int(r.get('inputTokens') or 0) + int(r.get('outputTokens') or 0)
                      + int(r.get('totalTokens') or 0),
            'detail': {k: v for k, v in r.items()
                       if k not in ('stage', 'at', 'tool', 'costUsd',
                                    'inputTokens', 'outputTokens', 'totalTokens',
                                    'cacheCreate', 'cacheRead', 'durationMs')},
        })

    machine = sum(s['ms'] for s in steps if not s['human'])
    human = sum(s['ms'] for s in steps if s['human'])
    return {
        'runId': str(run_id),
        'steps': steps,
        'totalMs': machine + human,
        'machineMs': machine,
        'humanMs': human,
        'costUsd': round(sum(s['costUsd'] for s in steps), 4),
        'tokens': sum(s['tokens'] for s in steps),
        'claudeCalls': sum(int(r.get('calls') or 0) for r in rows if r.get('tool') == 'claude'),
    }


def fmt_ms(ms):
    s = ms / 1000.0
    return '%5.1f초' % s if s < 60 else '%4.1f분' % (s / 60.0)


def show(run_id, save_json=False):
    m = summarize(run_id)
    if not m:
        print('실행 %s: metrics.jsonl 이 없습니다 (기록 도입 전 실행이거나 중단됨).' % run_id)
        return 1

    print('실행 %s' % m['runId'])
    print('%-16s %9s %8s %10s  %s' % ('단계', '소요', '토큰', '비용USD', '세부'))
    print('-' * 78)
    for s in m['steps']:
        mark = '  (사람)' if s['human'] else ''
        detail = ', '.join('%s=%s' % (k, v) for k, v in s['detail'].items()
                           if v not in (None, '', [], {}))
        print('%-16s %9s %8s %10s  %s%s' % (
            s['stage'], fmt_ms(s['ms']),
            s['tokens'] or '', ('%.4f' % s['costUsd']) if s['costUsd'] else '',
            detail[:34], mark))
    print('-' * 78)
    print('기계 %s · 사람 %s · 합계 %s · %s토큰 · $%.4f · Claude %d회' % (
        fmt_ms(m['machineMs']), fmt_ms(m['humanMs']), fmt_ms(m['totalMs']),
        m['tokens'], m['costUsd'], m['claudeCalls']))

    slow = max((s for s in m['steps'] if not s['human']), key=lambda s: s['ms'], default=None)
    if slow:
        pct = 100.0 * slow['ms'] / m['machineMs'] if m['machineMs'] else 0
        print('병목: %s (%s, 기계 시간의 %.0f%%)' % (slow['stage'], fmt_ms(slow['ms']), pct))

    if save_json:
        p = os.path.join(RUNS, str(run_id), 'metrics.json')
        json.dump(m, io.open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
        print('-> %s' % p)
    return 0


def show_all():
    """실행별 한 줄. 평가 표를 만들 때 이걸 붙여 쓴다."""
    ids = sorted((os.path.basename(os.path.dirname(p))
                  for p in glob.glob(os.path.join(RUNS, '*', 'metrics.jsonl'))),
                 key=lambda x: int(x) if x.isdigit() else 0)
    if not ids:
        print('기록이 있는 실행이 없습니다. 한 번 돌리면 생깁니다.')
        return 1
    print('%-6s %9s %9s %8s %10s %7s  %s' %
          ('실행', '기계', '사람', '토큰', '비용USD', 'Claude', '병목'))
    print('-' * 74)
    for rid in ids:
        m = summarize(rid)
        if not m:
            continue
        slow = max((s for s in m['steps'] if not s['human']),
                   key=lambda s: s['ms'], default=None)
        print('%-6s %9s %9s %8d %10.4f %7d  %s' % (
            rid, fmt_ms(m['machineMs']), fmt_ms(m['humanMs']),
            m['tokens'], m['costUsd'], m['claudeCalls'],
            slow['stage'] if slow else '-'))
    return 0


if __name__ == '__main__':
    args = [a for a in sys.argv[1:]]
    if '--all' in args:
        raise SystemExit(show_all())
    if not args or args[0].startswith('-'):
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(show(args[0], save_json='--json' in args))
