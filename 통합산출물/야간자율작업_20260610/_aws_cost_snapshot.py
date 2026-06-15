# -*- coding: utf-8 -*-
"""AWS 비용·리소스 스냅샷 생성 → data/aws_snapshot.json. 관리자 페이지가 이 파일을 읽어 표시.
(백엔드 EC2는 사용자 로컬 aws CLI를 못 쓰므로, 로컬에서 주기적으로 생성해 올리는 방식)
실행: python _aws_cost_snapshot.py  (aws configure 된 PC에서)"""
import json, subprocess, datetime
from pathlib import Path

AWS = r"C:\Program Files\Amazon\AWSCLIV2\aws.exe"
ROOT = Path(r"C:\Users\Admin\FILMN9")

def run(args):
    try:
        r = subprocess.run([AWS] + args, capture_output=True, text=True, timeout=40)
        return r.stdout.strip()
    except Exception as e:
        return f"err:{e}"

today = datetime.date.today()
start = today.replace(day=1).isoformat()
end = (today + datetime.timedelta(days=1)).isoformat()

cost = run(["ce", "get-cost-and-usage", "--time-period", f"Start={start},End={end}",
            "--granularity", "MONTHLY", "--metrics", "UnblendedCost",
            "--query", "ResultsByTime[0].Total.UnblendedCost.Amount", "--output", "text"])
# 서비스별 비용 top
svc = run(["ce", "get-cost-and-usage", "--time-period", f"Start={start},End={end}",
           "--granularity", "MONTHLY", "--metrics", "UnblendedCost",
           "--group-by", "Type=DIMENSION,Key=SERVICE",
           "--query", "ResultsByTime[0].Groups[].{svc:Keys[0],amt:Metrics.UnblendedCost.Amount}", "--output", "json"])
try: svc_list = json.loads(svc)
except Exception: svc_list = []

def n(args):
    v = run(args);
    try: return int(v)
    except Exception: return v

snapshot = {
    "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
    "month": today.strftime("%Y-%m"),
    "cost_usd": cost,
    "by_service": [s for s in svc_list if float(s.get("amt", "0") or 0) > 0][:8],
    "resources": {
        "EC2(running)": n(["ec2", "describe-instances", "--filters", "Name=instance-state-name,Values=running", "--query", "length(Reservations[].Instances[])", "--output", "text"]),
        "RDS": n(["rds", "describe-db-instances", "--query", "length(DBInstances[])", "--output", "text"]),
        "S3버킷": n(["s3api", "list-buckets", "--query", "length(Buckets[])", "--output", "text"]),
        "ElasticIP": n(["ec2", "describe-addresses", "--query", "length(Addresses[])", "--output", "text"]),
    },
    "note": "프리티어/크레딧 적용 중. EC2 t3.micro·RDS db.t3.micro는 프리티어. EIP는 연결 중 무료(미연결 시 소액). 크레딧 $158(Oct 15까지).",
}
out = ROOT / "data" / "aws_snapshot.json"
out.write_text(json.dumps(snapshot, ensure_ascii=False, indent=1), encoding="utf-8")
print("저장:", out)
print(json.dumps(snapshot, ensure_ascii=False, indent=1))
