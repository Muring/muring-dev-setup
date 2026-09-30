"""Deterministic offline rendering, separately fingerprinted for explicit approval."""
import base64
import hashlib
from html import escape
from pathlib import Path
from usage_store import digest, now, read


def fingerprint(template):
    font_dir = Path(template).resolve().parent.parent / 'assets/usage-font'
    assets = [hashlib.sha256(p.read_text(encoding='utf-8').encode() if p.suffix == '.txt' else p.read_bytes()).hexdigest() for p in sorted(font_dir.glob('*')) if p.is_file()]
    return digest([Path(template).read_text(encoding='utf-8'), Path(__file__).read_text(encoding='utf-8'), 'usage-v1', assets])

def num(n):
    return f'{n:,}'

def table(headings, rows):
    return '<div class="table-scroll"><table><thead><tr>' + ''.join('<th>' + escape(h) + '</th>' for h in headings) + '</tr></thead><tbody>' + ''.join('<tr>' + ''.join('<td>' + escape(str(v)) + '</td>' for v in row) + '</tr>' for row in rows) + '</tbody></table></div>'

def render(report, template, output, approval=None, preview=False, improvements=None):
    if not preview and (not approval or read(approval, {}).get('fingerprint') != fingerprint(template)):
        raise ValueError('HTML approval missing or template/renderer changed; JSON remains available')
    total = report['totals']
    coverage = []
    for d in report['devices']:
        health = d['health']
        coverage.append([d['device'], (d['until'] or '미수집'), health.get('state', '미상'), len(health.get('issues', []))])
    weekly = []
    max_tokens = max((w['totals']['total'] for w in report['weeks']), default=1) or 1
    charts = []
    for w in report['weeks']:
        t = w['totals']; d = w['diagnostics']
        weekly.append([w['week'], '기간 종료' if w['period_ended'] else '진행 중', '관측 기록 없음' if w['observation'] == 'no_records' else '관측됨', num(t['non_cache_read_input']), num(t['output']), num(t['responses']), f"{t['cache_read']/t['input']*100:.1f}%" if t['input'] else '—', d['large_outputs'], d['truncations'], d['repeated_calls']])
        charts.append('<div class="bar-row"><span>' + escape(w['week']) + '</span><div class="track"><i style="width:' + str(round(t['total'] / max_tokens * 100, 2)) + '%"></i></div><b>' + num(t['total']) + '</b></div>')
    groups = []
    for w in report['weeks']:
        for g in w['groups']:
            groups.append([w['week'], g['project'], g['tool'], g['model'], g['effort'], num(g['non_cache_read_input']), num(g['output']), num(g['responses'])])
    states = []
    for w in report['weeks']:
        for state, values in sorted(w['task_states'].items()):
            states.append([w['week'], state, num(values['total']), num(values['responses'])])
    timeline = []
    for event in improvements or []:
        timeline.append([event['date'], event['kind'], event['summary']])
    values = dict(
        title='AI 사용량 · 주간 기록', generated=escape(report['generated_at']),
        sync_state=escape(report.get('last_sync', {}).get('state', '미동기화')),
        sync_time=escape(report.get('last_sync', {}).get('last_success', '아직 없음')),
        badge='양식 확인용 미리보기' if preview else '승인된 양식',
        input=num(total['non_cache_read_input']), output=num(total['output']), responses=num(total['responses']),
        cache=f"{total['cache_read']/total['input']*100:.1f}%" if total['input'] else '—',
        coverage=table(['기기', '자료 기준 시각 (UTC)', '수집 상태', '확인 필요'], coverage),
        weekly=table(['주 시작 (KST)', '기간', '관측', '비캐시 입력', '출력', '응답', '캐시 읽기', '큰 출력', '잘림', '반복 호출'], weekly),
        charts=''.join(charts),
        groups=table(['주 시작', '프로젝트', '도구', '모델', '추론 수준', '비캐시 입력', '출력', '응답'], groups),
        tasks=table(['주 시작', '작업 상태', '전체 토큰', '응답'], states),
        task_details=table(['프로젝트 / 작업', '유형', '상태', '검증', '재작업', '관측 토큰'], [[t['project']+' / '+t['id'], t.get('type') or '미상', t['status'], '; '.join(c['name']+': '+c['result'] for c in t.get('verification') or []) or '미상', '미상' if t.get('rework') is None else str(t['rework']), num(t['totals']['total'])] for t in report['tasks']]),
        timeline=table(['적용일', '구분', '변경'], timeline),
        issues=escape(str(len(report['quality']['problems']))),
        fallback=escape(str(report['quality']['fallback_identities'])),
        diagnostics=table(['주 시작', '출력 수', '출력 문자', '확인된 실패', '결과 미상', 'KB 검색 실행', '결과 없음', '문서 선택', '실제 적용', '검색 언급', '압축'], [[w['week'], w['diagnostics']['outputs'], num(w['diagnostics']['output_chars']), w['diagnostics']['known_failed_outputs'], w['diagnostics']['unknown_output_outcomes'], w['diagnostics']['kb_searches'], w['diagnostics']['kb_empty_searches'], w['diagnostics']['kb_selections'], w['diagnostics']['kb_applications'], w['diagnostics']['kb_search_mentions'], w['diagnostics']['compactions']] for w in report['weeks']]))
    html = Path(template).read_text(encoding='utf-8')
    if '{{font_css}}' in html:
        font_dir = Path(template).resolve().parent.parent / 'assets/usage-font'
        encoded = base64.b64encode((font_dir / 'NanumGothic-Regular.ttf').read_bytes()).decode('ascii')
        values['font_css'] = "@font-face{font-family:UsageKorean;src:url(data:font/ttf;base64," + encoded + ") format('truetype');font-display:swap;}"
        values['font_license'] = escape((font_dir / 'OFL.txt').read_text(encoding='utf-8'))
    import re
    html = re.sub(r'\{\{([a-z_]+)\}\}', lambda m: values[m[1]], html)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix('.tmp')
    tmp.write_text(html, encoding='utf-8')
    tmp.replace(output)
