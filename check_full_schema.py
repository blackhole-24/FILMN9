import sqlite3
conn = sqlite3.connect(r'C:\Users\Admin\FILMN9\data\filmn9.db')
tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
print('=== Tables ===')
for t in tables:
    print(f'\n■ {t[0]}')
    cols = conn.execute(f'PRAGMA table_info({t[0]})').fetchall()
    for c in cols:
        # cid, name, type, notnull, dflt_value, pk
        pk = ' PK' if c[5] else ''
        nn = ' NOT NULL' if c[3] else ''
        print(f'  - {c[1]}: {c[2]}{pk}{nn}')
    # FK 정보
    fks = conn.execute(f'PRAGMA foreign_key_list({t[0]})').fetchall()
    if fks:
        print('  FK:')
        for fk in fks:
            print(f'    {fk[3]} → {fk[2]}.{fk[4]}')
conn.close()
