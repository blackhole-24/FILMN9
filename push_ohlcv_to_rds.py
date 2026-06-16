# -*- coding: utf-8 -*-
"""
push_ohlcv_to_rds.py — 로컬 SQLite 주가(ohlcv)의 최신 델타를 AWS RDS로 푸시.

배경: 로컬 일배치 스케줄러(ohlcv_daily_sync.py, 16:00)는 로컬 SQLite만 갱신하고
AWS RDS는 따라오지 않아 라이브 차트가 뒤처짐. 이 스크립트를 16:30에 이어 돌려
RDS를 로컬과 맞춘다. (6/20 전까지 임시 운영. 6/20부터는 EC2 일배치로 전환 예정.)

보안: 로컬 PC 공인IP가 매일 바뀌므로, 실행 시 ①현재 IP를 RDS 보안그룹 5432에
잠깐 열고 → ②푸시 → ③다시 닫는다(RDS는 평소 비공개 유지). AWS CLI는 IAM 인증이라
어떤 IP에서도 동작. DB 비밀번호는 .env(DATABASE_URL)를 런타임에 읽기만 한다.
"""
from __future__ import annotations
import os, re, sys, subprocess, sqlite3, urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve()
while ROOT != ROOT.parent and not (ROOT / "data" / "filmn9.db").exists():
    ROOT = ROOT.parent
LOCAL_DB = ROOT / "data" / "filmn9.db"
LOG = ROOT / "data" / "ohlcv_rds_push_log.txt"
AWS = r"C:\Program Files\Amazon\AWSCLIV2\aws.exe"
RDS_SG = "sg-02fd8d4e2bb16cabe"
REGION = "ap-northeast-2"


def log(msg: str):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def get_database_url() -> str | None:
    for envf in (ROOT / ".env", ROOT / "backend" / ".env"):
        if envf.exists():
            for ln in open(envf, encoding="utf-8"):
                if ln.strip().startswith("DATABASE_URL"):
                    return ln.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def my_ip() -> str:
    return urllib.request.urlopen("https://checkip.amazonaws.com", timeout=10).read().decode().strip()


def sg(action: str, ip: str):
    """authorize / revoke RDS 5432 for ip (실패·중복 무시)."""
    subprocess.run([AWS, "ec2", f"{action}-security-group-ingress", "--group-id", RDS_SG,
                    "--protocol", "tcp", "--port", "5432", "--cidr", f"{ip}/32",
                    "--region", REGION], capture_output=True, text=True)


def main():
    url = get_database_url()
    if not url:
        log("❌ DATABASE_URL 없음 — 중단"); return 1
    try:
        import psycopg
    except ImportError:
        log("❌ psycopg 미설치 — 중단"); return 1

    ip = my_ip()
    sg("authorize", ip)            # 내 IP 잠깐 열기
    try:
        with psycopg.connect(url, connect_timeout=20) as conn, conn.cursor() as cur:
            cur.execute("SELECT MAX(date) FROM ohlcv")
            rds_max = cur.fetchone()[0]
            rds_max = str(rds_max) if rds_max else "0000-00-00"
            lc = sqlite3.connect(LOCAL_DB)
            rows = lc.execute(
                "SELECT stock_code,date,open,high,low,close,volume FROM ohlcv WHERE date > ?",
                (rds_max,)).fetchall()
            lc.close()
            if not rows:
                log(f"동기화 불필요 (RDS·로컬 모두 {rds_max}까지)"); return 0
            cur.execute("DELETE FROM ohlcv WHERE date > %s", (rds_max,))
            cur.executemany(
                "INSERT INTO ohlcv (stock_code,date,open,high,low,close,volume) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s)", rows)
            conn.commit()
            cur.execute("SELECT MAX(date) FROM ohlcv")
            new_max = cur.fetchone()[0]
            log(f"✅ RDS 푸시 {len(rows)}행 ({rds_max} → {new_max})")
        return 0
    except Exception as e:
        log(f"❌ 오류: {type(e).__name__}: {str(e)[:120]}"); return 1
    finally:
        sg("revoke", ip)           # 다시 닫기 (RDS 비공개 복원)


if __name__ == "__main__":
    sys.exit(main())
