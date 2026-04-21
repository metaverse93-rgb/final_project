"""
trainset2232_clean.jsonl → trainset2232_clean_v2.jsonl
지명 / 인물명 / 회사명 / 기술용어 guide v2 완전 정제
"""
import json, re, sys
sys.stdout.reconfigure(encoding='utf-8')

INPUT  = 'eval/data/trainset2232_clean.jsonl'
OUTPUT = 'eval/data/trainset2232_clean_v2.jsonl'

# ── 교체 규칙 (순서 중요: 긴 패턴 먼저) ──────────────────────
RESTORE_MAP = [
    # 지명
    (re.compile(r'실리콘\s*밸리'),    'Silicon Valley'),
    (re.compile(r'샌프란시스코'),      'San Francisco'),
    (re.compile(r'워싱턴\s*D\.?C\.?'), 'Washington D.C.'),
    (re.compile(r'워싱턴'),            'Washington'),
    (re.compile(r'뉴욕'),              'New York'),
    (re.compile(r'런던'),              'London'),
    (re.compile(r'베이징'),            'Beijing'),
    (re.compile(r'보스턴'),            'Boston'),
    (re.compile(r'시애틀'),            'Seattle'),
    (re.compile(r'상하이'),            'Shanghai'),
    (re.compile(r'도쿄'),              'Tokyo'),
    # 인물명 (긴 이름 먼저)
    (re.compile(r'마크\s*저커버그'),   'Mark Zuckerberg'),
    (re.compile(r'순다르\s*피차이'),   'Sundar Pichai'),
    (re.compile(r'다리오\s*아모데이'), 'Dario Amodei'),
    (re.compile(r'데미스\s*하사비스'), 'Demis Hassabis'),
    (re.compile(r'제프리\s*힌튼'),     'Geoffrey Hinton'),
    (re.compile(r'사티아\s*나델라'),   'Satya Nadella'),
    (re.compile(r'샘\s*올트먼'),       'Sam Altman'),
    (re.compile(r'젠슨\s*황'),         'Jensen Huang'),
    (re.compile(r'일론\s*머스크'),     'Elon Musk'),
    (re.compile(r'얀\s*르쿤'),         'Yann LeCun'),
    (re.compile(r'그렉\s*브록만'),     'Greg Brockman'),
    (re.compile(r'일리야\s*수츠케버'), 'Ilya Sutskever'),
    # 회사명 (인텔리전스 오탐 제외)
    (re.compile(r'인텔(?!리)'),        'Intel'),
    # 기술용어
    (re.compile(r'하이퍼파라미터'),    'hyperparameter'),
    (re.compile(r'파라미터'),          'parameter'),
]

def clean_text(text: str) -> str:
    for pattern, replacement in RESTORE_MAP:
        text = pattern.sub(replacement, text)
    return text

# ── 실행 ─────────────────────────────────────────────────────
changed = 0
total   = 0

with open(INPUT, encoding='utf-8') as fin, \
     open(OUTPUT, 'w', encoding='utf-8') as fout:

    for line in fin:
        d = json.loads(line)
        total += 1
        original = d['messages'][-1]['content']
        cleaned  = clean_text(original)

        if cleaned != original:
            changed += 1
            d['messages'][-1]['content'] = cleaned

        fout.write(json.dumps(d, ensure_ascii=False) + '\n')

print(f'총 {total}건 중 {changed}건 수정')
print(f'출력: {OUTPUT}')

# ── 검증 ─────────────────────────────────────────────────────
print('\n=== 검증: 잔존 위반 건수 ===')
with open(OUTPUT, encoding='utf-8') as f:
    texts = [json.loads(l)['messages'][-1]['content'] for l in f]

checks = {
    '뉴욕': 'New York', '런던': 'London', '샌프란시스코': 'San Francisco',
    '실리콘밸리': 'Silicon Valley', '워싱턴': 'Washington', '베이징': 'Beijing',
    '보스턴': 'Boston', '시애틀': 'Seattle', '상하이': 'Shanghai', '도쿄': 'Tokyo',
    '샘 올트먼': 'Sam Altman', '젠슨 황': 'Jensen Huang', '일론 머스크': 'Elon Musk',
    '마크 저커버그': 'Mark Zuckerberg', '다리오 아모데이': 'Dario Amodei',
    '순다르 피차이': 'Sundar Pichai', '파라미터': 'parameter',
    '하이퍼파라미터': 'hyperparameter',
    '파인튜닝': 'Fine-tuning', '임베딩': 'Embedding', '아마존': 'Amazon',
}
all_clean = True
for kw, eng in checks.items():
    cnt = sum(1 for t in texts if kw in t)
    status = '✅' if cnt == 0 else '❌'
    if cnt > 0:
        all_clean = False
    print(f'  {status} {kw}: {cnt}건')

print()
print('완전 정제 완료 ✅' if all_clean else '잔존 항목 있음 — 수동 확인 필요')
