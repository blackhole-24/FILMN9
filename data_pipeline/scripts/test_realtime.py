import urllib.request, json

r = urllib.request.urlopen('http://localhost:8000/api/realtime/090430', timeout=5)
d = json.loads(r.read())
print('=== 090430 실시간 ===')
price = d['price']
mc = d['market_cap']
pt = d['price_time']
mo = d['is_market_open']
print(f'주가: {price:,}원')
print(f'시총(raw): {mc:,.0f}원')
print(f'시총(조): {mc/1e12:.2f}조')
print(f'시각: {pt}')
print(f'장중: {mo}')
