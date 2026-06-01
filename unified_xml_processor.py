"""
═══════════════════════════════════════════════════════════════════
  FILMN9 통합 XML 처리 자동화 (3000개 종목 원클릭)
═══════════════════════════════════════════════════════════════════

[기능]
1. 감사보고서 → 사업보고서 재다운로드
2. 전체 XML 일괄 파싱 + DB 재적재
3. 검증 보고서 생성

[사용법]
python unified_xml_processor.py --step all       # 전체 자동 진행
python unified_xml_processor.py --step audit     # 감사보고서만 재다운로드
python unified_xml_processor.py --step parse     # 파싱만
python unified_xml_processor.py --step verify    # 검증만

[OpenAI] 0회 / $0
[작성일] 2026-05-27
═══════════════════════════════════════════════════════════════════
"""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(r"C:\Users\Admin\FILMN9")

STEPS = {
    "audit": ("감사보고서 재다운로드", "redownload_audit.py"),
    "parse": ("XML 파싱 + DB 재적재", "parse_business_report_xml.py --all"),
    "verify": ("검증 보고서", "verify_2025.py"),
}

def run_step(name: str, script_args: str):
    print("\n" + "=" * 70)
    print(f"  ▶ {name}")
    print("=" * 70)
    cmd = f"python {script_args}"
    result = subprocess.run(
        cmd, shell=True, cwd=str(ROOT),
        env={**__import__('os').environ, "PYTHONIOENCODING": "utf-8"},
    )
    if result.returncode != 0:
        print(f"  ❌ {name} 실패 (exit={result.returncode})")
        return False
    print(f"  ✅ {name} 완료")
    return True

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--step", default="all",
                   choices=["all", "audit", "parse", "verify"])
    args = p.parse_args()

    if args.step == "all":
        for name, (desc, script) in STEPS.items():
            ok = run_step(desc, script)
            if not ok:
                sys.exit(1)
    else:
        desc, script = STEPS[args.step]
        run_step(desc, script)

if __name__ == "__main__":
    main()
