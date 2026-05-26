import sys
sys.path.insert(0, r'C:\Users\Admin\FILMN9')
from api.routers.extras import get_health, get_realtime, get_news

print('=== 건전성 지표 테스트 ===')
for code in ['090430', '009150', '035420']:
    try:
        r = get_health(code)
        m = r['metrics']
        dr = m['debt_ratio']
        cr = m['current_ratio']
        om = m['op_margin']
        print(f"{code} [{r['fiscal_year']}]:")
        print(f"  부채비율: {dr['value']}% [{dr['grade']}]")
        print(f"  유동비율: {cr['value']}% [{cr['grade']}]")
        print(f"  영업이익률: {om['value']}% [{om['grade']}]")
        print(f"  종합: {r['overall_grade']}")
    except Exception as e:
        print(f'{code}: ERROR - {e}')

print('\n=== 실시간 주가 테스트 ===')
for code in ['090430', '009150', '035420']:
    try:
        r = get_realtime(code)
        print(f"{code}: {r['price']:,}원, 시총={r['market_cap']:,}, 시각={r['price_time']}, 장중={r['is_market_open']}")
    except Exception as e:
        print(f'{code}: ERROR - {e}')

print('\n=== 뉴스 테스트 (090430) ===')
try:
    r = get_news('090430', limit=3)
    for n in r['items']:
        print(f"  [{n['pubdate']}] {n['title'][:50]}")
        print(f"  링크: {n['link'][:60]}")
except Exception as e:
    print(f'ERROR: {e}')
