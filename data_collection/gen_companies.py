import pandas as pd
import sys
sys.stdout.reconfigure(encoding='utf-8')

path = r'C:\Users\Admin\Documents\KPMG\FILMN9\데이터 수집\kospi_kosdaq_team_assignment.xlsx'
sheets = pd.read_excel(path, sheet_name=None)
df4 = sheets['팀원4 이형주']

col_corp = df4.columns[9]
col_code = df4.columns[8]

lines = []
for _, row in df4.iterrows():
    name = str(row[col_corp]).strip()
    code = str(row[col_code]).strip()
    if len(code) > 6:
        code = code[-6:]
    code = code.zfill(6)
    lines.append(f'    ("팀원4", "{code}", "{name}"),')

content = '"""\n팀원4 이형주 — 담당 기업 목록 (693개)\nKOSPI: 237개 / KOSDAQ: 456개\n"""\n\nCOMPANIES = [\n'
content += '\n'.join(lines)
content += '\n]\n\nif __name__ == "__main__":\n    print(f"총 {len(COMPANIES)}개 기업")\n    for c in COMPANIES[:5]:\n        print(c)\n    print("...")\n'

with open(r'C:\Users\Admin\FILMN9\data_collection\companies.py', 'w', encoding='utf-8') as f:
    f.write(content)

print(f"완료: {len(lines)}개 기업 생성")
print("첫 3개:", lines[:3])
print("마지막 3개:", lines[-3:])
