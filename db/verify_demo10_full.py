"""
db/verify_demo10_full.py
========================
시연 10종목이 SQLite + MongoDB 모든 출처에서 정상 응답하는지 최종 검증.
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

print(f"{'code':<8} {'이름':<22} {'company':<8} {'fin':<6} {'ohlcv':<10} {'history':<10} {'현재가':<14}")
print("-" * 88)

ok_count = 0
for code, name in DEMO_10:
    try:
        r = urllib.request.urlopen(f"{API}/api/overview/{code}", timeout=5)
        d = json.loads(r.read().decode())
        ci    = "✅" if d["tab1"]["company"]    else "❌"
        fin   = "✅3년" if d["tab1"]["financials"] else "❌"
        ohcnt = d["tab1"]["ohlcv"]["count"]    if d["tab1"]["ohlcv"] else 0
        hist  = "✅"   if d["tab1"]["history"]  else "❌"
        price = d["header"]["current_price"]   if d["header"] else "?"
        all_ok = ci == "✅" and "✅" in fin and ohcnt > 0 and hist == "✅"
        if all_ok:
            ok_count += 1
        print(f"{code:<8} {name:<22} {ci:<8} {fin:<6} {ohcnt:>6,}일   {hist:<10} {price:>10,}원")
    except Exception as e:
        print(f"{code:<8} {name:<22} ❌ {e}")

print("-" * 88)
print(f"\n✅ 풀세트 완성: {ok_count}/{len(DEMO_10)} 종목")
