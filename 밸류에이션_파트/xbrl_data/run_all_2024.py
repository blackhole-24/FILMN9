import os
import time
import sys

# xbrl_data.py 파일에서 핵심 함수를 불러옵니다.
from xbrl_data_v2 import extract_company


def run_automation(csv_file="전종목리스트.csv", target_year=2024, out_dir="./output_json"):
    # 1. 결과물을 저장할 폴더 생성
    os.makedirs(out_dir, exist_ok=True)
    
    # 2. 전종목 리스트 읽기 및 데이터 정제
    company_list = []
    try:
        with open(csv_file, 'r', encoding='utf-8') as f:
            for line in f:
                # 양쪽 공백/줄바꿈 제거
                clean_name = line.strip()
                
                # 빈 줄이거나 '[source' 같은 메타 태그가 포함된 줄은 제외
                if not clean_name or clean_name.startswith('['):
                    continue
                    
                company_list.append(clean_name)
    except FileNotFoundError:
        print(f"❌ {csv_file} 파일을 찾을 수 없습니다.")
        sys.exit(1)

    total_count = len(company_list)
    print(f"✅ 총 {total_count}개의 종목을 읽어왔습니다. 추출을 시작합니다.\n")

    # 3. 실패한 종목을 기록할 리스트
    failed_companies = []

    # 4. 반복문을 통한 자동화 추출
    for index, company in enumerate(company_list, start=1):

        print(f"▶ [{index}/{total_count}] '{company}' 추출 시도 중...")
        
        try:
            # xbrl_data.py의 extract_company 함수 호출
            # verbose=False로 설정하여 개별 종목의 긴 요약 출력을 숨길 수 있습니다.
            extract_company(
                name_or_code=company, 
                year=target_year, 
                outdir=out_dir, 
                save=True, 
                verbose=False 
            )
            print(f"  └─ 완료!")
            
        except Exception as e:
            # 특정 종목에서 에러가 발생해도 전체 프로그램이 멈추지 않도록 예외 처리
            print(f"  └─ ❌ 오류 발생: {e}")
            failed_companies.append((company, str(e)))
            
        # DART API 과부하 방지를 위한 대기 시간 (3초 권장)
        time.sleep(3)

    # 5. 최종 결과 리포트
    print("\n" + "="*50)
    print("🎉 모든 작업이 완료되었습니다!")
    print(f"총 대상: {total_count}건 | 처리: {total_count}건 "
          f" | 실패: {len(failed_companies)}건")
    print(f"저장 폴더: {out_dir}")


    if failed_companies:
        print("\n[실패한 종목 목록]")
        for comp, err in failed_companies:
            print(f"- {comp} (사유: {err})")

if __name__ == "__main__":
    # 조회할 회계연도를 여기에 입력하세요. (기본값: 2024)
    run_automation(csv_file="전종목리스트.csv", target_year=2024, out_dir="./xbrl_results_2024")