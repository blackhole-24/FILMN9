"""휘주님 142개 history 실제 스키마 확인용"""
import json
from pathlib import Path

# 030200 KT, 002790 아모레퍼시픽홀딩스, 033780 KT&G 3개 샘플
sample_codes = ['030200', '002790', '033780', '034220', '138930']
hist_dir = Path('C:/Users/Admin/FILMN9/data/parsed_history')

print('=== 휘주님 brief 스키마 (5개 샘플) ===\n')
for code in sample_codes:
    files = list(hist_dir.glob(f'{code}_*.json'))
    if not files:
        print(f'[{code}] 파일 없음')
        continue
    d = json.loads(files[0].read_text(encoding='utf-8'))
    brief = d.get('brief', {})
    print(f'[{code}] {files[0].name}')
    print(f'  brief 키들: {list(brief.keys())}')
    if 'price_factors' in brief:
        pf = brief['price_factors']
        print(f'  price_factors: {len(pf)}개')
    if 'main_customers' in brief:
        mc = brief['main_customers']
        print(f'  main_customers: {len(mc)}자')
    print()

# 한 종목 풀 내용 출력
print('=' * 60)
print('=== 030200 KT 전체 brief ===')
print('=' * 60)
files = list(hist_dir.glob('030200_*.json'))
if files:
    d = json.loads(files[0].read_text(encoding='utf-8'))
    brief = d.get('brief', {})
    for k, v in brief.items():
        print(f'\n[{k}]')
        if isinstance(v, list):
            for i, item in enumerate(v, 1):
                if isinstance(item, dict):
                    f = item.get('factor', item.get('field', '?'))
                    de = item.get('detail', item.get('evidence_text', str(item)))[:150]
                    print(f'  {i}. {f}: {de}')
                else:
                    print(f'  {i}. {item}')
        else:
            print(f'  {v[:300]}')
