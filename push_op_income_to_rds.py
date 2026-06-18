# -*- coding: utf-8 -*-
"""
push_op_income_to_rds.py — 로컬 SQLite financials.op_income 을 AWS RDS로 동기화.
_backfill_op_income.py 로 채운 영업이익(영업순손익 등 변형)을 라이브(RDS)에도 반영.
보안: 실행 시 내 공인IP를 RDS SG 5432에 잠깐 열고 → UPDATE → 다시 닫는다.
op_income IS NOT NULL 인 행만 RDS에 덮어씀(절대 null로 만들지 않음). 비번은 .env에서 읽기만.
"""
import subprocess, sqlite3, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOCAL_DB = ROOT / "data" / "filmn9.db"
AWS = r"C:\Program Files\Amazon\AWSCLIV2\aws.exe"
RDS_SG = "sg-02fd8d4e2bb16cabe"
REGION = "ap-northeast-2"

def get_database_url():
    for envf in (ROOT / ".env", ROOT / "backend" / ".env"):
        if envf.exists():
            for ln in open(envf, encoding="utf-8"):
                if ln.strip().startswith("DATABASE_URL"):
                    return ln.split("=", 1)[1].strip().strip('"').strip("'")
    return None

def my_ip():
    return urllib.request.urlopen("https://checkip.amazonaws.com", timeout=10).read().decode().strip()

def sg(action, ip):
    subprocess.run([AWS, "ec2", f"{action}-security-group-ingress", "--group-id", RDS_SG,
                    "--protocol", "tcp", "--port", "5432", "--cidr", f"{ip}/32",
                    "--region", REGION], capture_output=True, text=True)

def main():
    url = get_database_url()
    if not url:
        print("❌ DATABASE_URL 없음"); return 1
    import psycopg
    lc = sqlite3.connect(str(LOCAL_DB))
    rows = lc.execute(
        "SELECT op_income, stock_code, fiscal_year, reprt_code FROM financials "
        "WHERE op_income IS NOT NULL").fetchall()
    lc.close()
    print(f"동기화 대상(op_income 보유): {len(rows)}행")
    ip = my_ip(); sg("authorize", ip)
    try:
        with psycopg.connect(url, connect_timeout=20) as conn, conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM financials WHERE op_income IS NULL")
            before = cur.fetchone()[0]
            cur.executemany(
                "UPDATE financials SET op_income=%s WHERE stock_code=%s AND fiscal_year=%s "
                "AND reprt_code IS NOT DISTINCT FROM %s", rows)
            conn.commit()
            cur.execute("SELECT COUNT(*) FROM financials WHERE op_income IS NULL")
            after = cur.fetchone()[0]
            # 검증: 원익IPS
            cur.execute("SELECT fiscal_year,reprt_code,op_income FROM financials "
                        "WHERE stock_code='240810' ORDER BY fiscal_year DESC")
            print(f"✅ RDS UPDATE 완료. op_income NULL: {before} → {after}")
            print("원익IPS(240810) RDS op_income:")
            for r in cur.fetchall():
                print("  ", r)
    finally:
        sg("revoke", ip)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
