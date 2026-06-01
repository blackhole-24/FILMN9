"""
db/verify_demo10.py
===================
시연 10종목이 /api/overview 에서 정상 응답하는지 검증.
"""
import urllib.request, json

API = "http://localhost:8000"
DEMO_10 = [
    ("002790", "아모레퍼시픽홀딩스"), ("003490", "대한항공"),
    ("009240", "한샘"),             ("030200", "KT"),
    ("033780", "KT&G"),             ("034220", "LG디스플레이"),
    ("071840", "롯데하이마트"),     ("138930", "BNK금융지주"),
    ("267260", "HD현대일렉트릭"),   ("373220", "LG에너지솔루션"),
]

print(f'{"code":<8} {"이름":<18} {"company":<8} {"fin":<6} {"ohlcv":<8} {"가격":<12} {"등락":<10}')
print("-" * 80)

for code, name in DEMO_10:
    try:
        r = urllib.request.urlopen(f"{API}/api/overview/{code}", timeout=5)
        d = json.loads(r.read().decode())
        ci   = "O" if d["tab1"]["company"]      else "X"
        fin  = len(d["tab1"]["financials"]["fiscal_years"]) if d["tab1"]["financials"] else 0
        ohcnt = d["tab1"]["ohlcv"]["count"]      if d["tab1"]["ohlcv"]      else 0
        price = d["header"]["current_price"]     if d["header"]             else None
        pct   = d["header"]["change_pct"]        if d["header"]             else None
        sign  = "+" if pct and pct > 0 else ""
        print(f'{code:<8} {name:<18} {ci:<8} {fin}년치    {ohcnt:>5,}일   {price:>10,}원  {sign}{pct}%')
    except Exception as e:
        print(f'{code:<8} {name:<18} ❌ {e}')
