"""Analyze one stock on demand and reuse same-date results.

Examples
--------
  python scripts/analyze_stock_cached.py 삼성전기
  python scripts/analyze_stock_cached.py 009150
  python scripts/analyze_stock_cached.py 삼성전기 --refresh
  python scripts/analyze_stock_cached.py 삼성전기 --report-date 20260528
  python scripts/analyze_stock_cached.py --list
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import certifi
from dotenv import load_dotenv
from pymongo import ASCENDING, MongoClient
from pymongo.collection import Collection
from pykrx import stock as krx

from run_daily_factor_report import (
    BASE_DIR,
    DEFAULT_OUTPUT_DIR,
    KST,
    LLM_MODEL,
    TARGETS,
    USD_KRW_ESTIMATE,
    Target,
    build_evidence_pack,
    calc_return_snapshot,
    estimate_openai_cost,
    load_env,
    summarize_factors,
)


PROMPT_VERSION = "v1"
DEFAULT_MONGO_DB = "filmn9"
DEFAULT_MONGO_COLLECTION = "daily_factor_reports"
GENERIC_TOPICS = ("주가", "실적", "공시", "목표가", "수급")
STOCK_MASTER_CANDIDATES = (
    BASE_DIR / "data" / "ticker_universe.csv",
    BASE_DIR / "prompt_test" / "ticker_universe.csv",
)


load_dotenv(BASE_DIR / ".env")


def normalize_query(value: str) -> str:
    return re.sub(r"\s+", "", value).upper()


def normalize_report_date(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = re.sub(r"[^0-9]", "", value)
    if len(cleaned) != 8:
        raise ValueError("--report-date는 YYYYMMDD 또는 YYYY-MM-DD 형식이어야 합니다.")
    return cleaned


def report_date_to_folder(value: str) -> str:
    return f"{value[:4]}-{value[4:6]}-{value[6:]}"


def load_stock_master() -> list[dict[str, str]]:
    for path in STOCK_MASTER_CANDIDATES:
        if path.exists():
            with path.open("r", encoding="utf-8-sig", newline="") as f:
                return list(csv.DictReader(f))
    return []


def target_from_master_row(row: dict[str, str]) -> Target:
    sector = row.get("industry") or row.get("wics") or "미분류"
    topics = tuple(dict.fromkeys([*GENERIC_TOPICS, sector, row.get("wics", "")]))
    return Target(
        stock_code=row["stock_code"],
        corp_name=row["corp_name"],
        market=row.get("market") or "KOSPI",
        sector=sector,
        topics=tuple(topic for topic in topics if topic),
        peers={},
    )


def find_target_from_stock_master(query: str) -> Target | None:
    q = normalize_query(query)
    exact_matches: list[Target] = []
    partial_matches: list[Target] = []

    for row in load_stock_master():
        stock_code = row.get("stock_code", "")
        corp_name = row.get("corp_name", "")
        if not stock_code or not corp_name:
            continue
        normalized_code = normalize_query(stock_code)
        normalized_name = normalize_query(corp_name)
        if q == normalized_code or q == normalized_name:
            exact_matches.append(target_from_master_row(row))
        elif q in normalized_name or normalized_name in q:
            partial_matches.append(target_from_master_row(row))

    matches = exact_matches or partial_matches
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        names = ", ".join(f"{target.stock_code} {target.corp_name}" for target in matches[:10])
        raise ValueError(f"검색어가 여러 종목과 매칭됩니다: {names}")
    return None


def detect_market(stock_code: str) -> str:
    for market in ("KOSPI", "KOSDAQ", "KONEX"):
        try:
            if stock_code in krx.get_market_ticker_list(market=market):
                return market
        except Exception:
            continue
    return "KOSPI"


def make_generic_target(stock_code: str) -> Target:
    master_target = find_target_from_stock_master(stock_code)
    if master_target:
        return master_target
    if not re.fullmatch(r"[0-9A-Z]{6}", stock_code):
        raise ValueError(f"종목코드는 6자리 숫자/문자 조합이어야 합니다: {stock_code}")
    corp_name = krx.get_market_ticker_name(stock_code)
    if not isinstance(corp_name, str) or not corp_name or corp_name == stock_code:
        raise ValueError(f"pykrx 종목 마스터에서 종목명을 찾지 못했습니다: {stock_code}")
    return Target(
        stock_code=stock_code,
        corp_name=corp_name,
        market=detect_market(stock_code),
        sector="미분류",
        topics=GENERIC_TOPICS,
        peers={},
    )


def find_target_from_market_master(query: str) -> Target:
    master_target = find_target_from_stock_master(query)
    if master_target:
        return master_target

    q = normalize_query(query)
    exact_matches: list[Target] = []
    partial_matches: list[Target] = []

    for market in ("KOSPI", "KOSDAQ", "KONEX"):
        try:
            tickers = krx.get_market_ticker_list(market=market)
        except Exception:
            continue
        for stock_code in tickers:
            corp_name = krx.get_market_ticker_name(stock_code)
            normalized_name = normalize_query(corp_name)
            if normalized_name == q:
                exact_matches.append(make_generic_target(stock_code))
            elif q in normalized_name or normalized_name in q:
                partial_matches.append(make_generic_target(stock_code))

    matches = exact_matches or partial_matches
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        names = ", ".join(f"{target.stock_code} {target.corp_name}" for target in matches[:10])
        raise ValueError(f"검색어가 여러 종목과 매칭됩니다: {names}")
    raise ValueError(f"종목 마스터에서 찾지 못했습니다: {query}")


def find_target(query: str) -> Target:
    q = normalize_query(query)
    if q in TARGETS:
        return TARGETS[q]
    if re.fullmatch(r"[0-9A-Z]{6}", q):
        return make_generic_target(q)

    matches = [
        target
        for target in TARGETS.values()
        if q in normalize_query(target.corp_name) or normalize_query(target.corp_name) in q
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        names = ", ".join(f"{target.stock_code} {target.corp_name}" for target in matches)
        raise ValueError(f"검색어가 여러 종목과 매칭됩니다: {names}")

    return find_target_from_market_master(query)


def list_targets() -> None:
    print("상세 설정이 등록된 검증 종목")
    for target in TARGETS.values():
        print(f"- {target.stock_code} {target.corp_name} ({target.market}/{target.sector})")
    master_count = len(load_stock_master())
    print(f"\n그 외 종목도 종목명 또는 종목코드로 요청할 수 있습니다. 종목 마스터: {master_count:,}개")


def get_mongo_collection(args: argparse.Namespace) -> Collection | None:
    if args.storage == "json":
        return None
    uri = os.getenv("MONGO_URI", "").strip()
    if not uri:
        if args.storage == "mongo":
            raise RuntimeError(".env에 MONGO_URI가 없어 MongoDB 캐시를 사용할 수 없습니다.")
        print("[WARN] MONGO_URI 없음: MongoDB 저장은 건너뛰고 JSON만 사용합니다.")
        return None

    client = MongoClient(uri, tlsCAFile=certifi.where(), serverSelectionTimeoutMS=8000)
    client.admin.command("ping")
    coll = client[args.mongo_db][args.mongo_collection]
    coll.create_index(
        [
            ("stock_code", ASCENDING),
            ("trade_date", ASCENDING),
            ("model", ASCENDING),
            ("prompt_version", ASCENDING),
        ],
        unique=True,
        name="daily_factor_cache_key",
    )
    return coll


def mongo_cache_filter(target: Target, trade_date: str, prompt_version: str, model: str | None = LLM_MODEL) -> dict:
    return {
        "stock_code": target.stock_code,
        "trade_date": trade_date,
        "model": model,
        "prompt_version": prompt_version,
    }


def mongo_source_label(coll: Collection) -> str:
    return f"MongoDB {coll.database.name}.{coll.name}"


def find_mongo_cached_report(
    coll: Collection | None,
    target: Target,
    trade_date: str,
    prompt_version: str,
) -> dict | None:
    if coll is None:
        return None
    doc = coll.find_one(
        {
            **mongo_cache_filter(target, trade_date, prompt_version),
            "report": {"$ne": None},
            "$or": [{"error": None}, {"error": {"$exists": False}}],
        },
        {"_id": 0},
    )
    return doc


def cache_candidates(output_dir: Path, target: Target, trade_date: str) -> list[Path]:
    save_dir = output_dir / trade_date
    if not save_dir.exists():
        return []
    return sorted(
        save_dir.glob(f"{target.stock_code}_*_daily_factor_report.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def find_cached_report(output_dir: Path, target: Target, trade_date: str) -> tuple[Path, dict] | None:
    for path in cache_candidates(output_dir, target, trade_date):
        payload = read_json(path)
        if payload.get("error"):
            continue
        if payload.get("report"):
            return path, payload
    return None


def normalize_payload_for_mongo(target: Target, payload: dict, prompt_version: str) -> dict:
    report = payload.get("report") or {}
    pack = payload.get("evidence_pack") or {}
    price = pack.get("price") or {}
    trade_date = price.get("trade_date")
    model = report.get("_llm_model", LLM_MODEL) if report else None
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    return {
        "stock_code": target.stock_code,
        "corp_name": target.corp_name,
        "trade_date": trade_date,
        "model": model,
        "prompt_version": prompt_version,
        "report": payload.get("report"),
        "evidence_pack": pack,
        "error": payload.get("error"),
        "cost": payload.get("cost") or estimate_openai_cost(report.get("_usage", {})),
        "cache_meta": payload.get("cache_meta") or {
            "cache_key": {
                "stock_code": target.stock_code,
                "trade_date": trade_date,
                "model": model,
                "prompt_version": prompt_version,
            },
            "generated_at": now,
        },
        "updated_at": now,
    }


def save_mongo_payload(coll: Collection, target: Target, payload: dict, prompt_version: str) -> str:
    doc = normalize_payload_for_mongo(target, payload, prompt_version)
    if not doc.get("trade_date"):
        raise RuntimeError("MongoDB 저장 실패: trade_date가 없습니다.")
    coll.update_one(
        mongo_cache_filter(target, doc["trade_date"], prompt_version, doc.get("model")),
        {
            "$set": doc,
            "$setOnInsert": {"created_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")},
        },
        upsert=True,
    )
    return mongo_source_label(coll)


def safe_filename(value: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", value)


def build_cached_payload(
    target: Target,
    report: dict | None,
    pack: dict,
    prompt_version: str,
    cost: dict | None = None,
    error: str | None = None,
) -> dict:
    trade_date = pack.get("price", {}).get("trade_date", datetime.now(KST).strftime("%Y-%m-%d"))
    return {
        "report": report,
        "evidence_pack": pack,
        "error": error,
        "cache_meta": {
            "cache_key": {
                "stock_code": target.stock_code,
                "trade_date": trade_date,
                "model": None if report is None else report.get("_llm_model", LLM_MODEL),
                "prompt_version": prompt_version,
            },
            "generated_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"),
        },
        "cost": cost or {},
    }


def save_json_payload(output_dir: Path, target: Target, payload: dict) -> Path:
    trade_date = payload.get("evidence_pack", {}).get("price", {}).get(
        "trade_date",
        datetime.now(KST).strftime("%Y-%m-%d"),
    )
    save_dir = output_dir / trade_date
    save_dir.mkdir(parents=True, exist_ok=True)
    path = save_dir / f"{target.stock_code}_{safe_filename(target.corp_name)}_daily_factor_report.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def print_result(source: Path | str, payload: dict, from_cache: bool) -> None:
    report = payload.get("report") or {}
    pack = payload.get("evidence_pack") or {}
    price = pack.get("price", {})
    market = pack.get("market") or {}
    usage = report.get("_usage", {})
    cost = payload.get("cost") or estimate_openai_cost(usage)

    print("\n분석 결과")
    print(f"- 종목: {price.get('corp_name') or report.get('corp_name')} ({price.get('stock_code') or report.get('stock_code')})")
    print(f"- 기준 거래일: {price.get('trade_date')}")
    print(f"- 1D 수익률: {price.get('return_1d')}%")
    if market:
        excess = round((price.get("return_1d") or 0) - (market.get("return_1d") or 0), 2)
        print(f"- 시장 수익률: {market.get('return_1d')}% / 초과수익률: {excess}%p")
    print(f"- 최근 패턴: {report.get('recent_pattern') or price.get('pattern', {}).get('label')}")
    print(f"- 요약: {report.get('headline', 'LLM 요약 없음')}")

    factors = report.get("factors") or []
    if factors:
        print("- 요인 3가지:")
        for factor in factors:
            print(f"  {factor.get('rank')}. {factor.get('title')} ({factor.get('confidence')})")

    if from_cache:
        print("- OpenAI 추가 호출: 없음 (저장된 결과 사용)")
    elif cost:
        print(
            "- OpenAI 사용량: "
            f"input {cost.get('input_tokens', 0):,} / "
            f"output {cost.get('output_tokens_billed', 0):,} / "
            f"${cost.get('estimated_cost_usd', 0):.6f} "
            f"(~{cost.get('estimated_cost_krw', 0):.2f}원)"
        )
    print(f"- 저장 위치: {source}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="종목 검색형 AI 요인 분석 실행 및 같은 날짜 결과 재사용")
    parser.add_argument("query", nargs="?", help="종목명 또는 종목코드. 예: 삼성전기 또는 009150")
    parser.add_argument("--report-date", type=str, default=None, help="기준일 YYYYMMDD 또는 YYYY-MM-DD")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="결과 저장 폴더")
    parser.add_argument("--storage", choices=["mongo", "json", "both"], default="mongo", help="캐시/저장 위치")
    parser.add_argument("--mongo-db", type=str, default=os.getenv("MONGO_DB", DEFAULT_MONGO_DB), help="MongoDB DB명")
    parser.add_argument(
        "--mongo-collection",
        type=str,
        default=os.getenv("MONGO_DAILY_FACTOR_COLLECTION", DEFAULT_MONGO_COLLECTION),
        help="MongoDB 컬렉션명",
    )
    parser.add_argument("--refresh", action="store_true", help="저장 결과가 있어도 새로 분석")
    parser.add_argument("--no-llm", action="store_true", help="OpenAI 호출 없이 근거 데이터만 저장")
    parser.add_argument("--prompt-version", type=str, default=PROMPT_VERSION, help="캐시 구분용 프롬프트 버전")
    parser.add_argument("--list", action="store_true", help="현재 지원 종목 목록 출력")
    return parser.parse_args()


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    args.output_dir = args.output_dir.resolve()

    if args.list:
        list_targets()
        return
    if not args.query:
        raise SystemExit("종목명 또는 종목코드를 입력하세요. 예: python scripts/analyze_stock_cached.py 삼성전기")

    report_date = normalize_report_date(args.report_date)
    target = find_target(args.query)
    mongo_coll = get_mongo_collection(args)

    if report_date and not args.refresh and not args.no_llm:
        trade_date_folder = report_date_to_folder(report_date)
        mongo_cached = find_mongo_cached_report(mongo_coll, target, trade_date_folder, args.prompt_version)
        if mongo_cached:
            print(f"MongoDB 캐시 사용: {target.corp_name} / {trade_date_folder}")
            print_result(mongo_source_label(mongo_coll), mongo_cached, from_cache=True)
            return

        json_cached = find_cached_report(args.output_dir, target, trade_date_folder)
        if json_cached:
            path, payload = json_cached
            if mongo_coll is not None:
                save_mongo_payload(mongo_coll, target, payload, args.prompt_version)
            print(f"캐시 사용: {target.corp_name} / {report_date_to_folder(report_date)}")
            print_result(path, payload, from_cache=True)
            return

    price = calc_return_snapshot(target, report_date)
    trade_date = price["trade_date"]
    if not args.refresh and not args.no_llm:
        mongo_cached = find_mongo_cached_report(mongo_coll, target, trade_date, args.prompt_version)
        if mongo_cached:
            print(f"MongoDB 캐시 사용: {target.corp_name} / {trade_date}")
            print_result(mongo_source_label(mongo_coll), mongo_cached, from_cache=True)
            return

        json_cached = find_cached_report(args.output_dir, target, trade_date)
        if json_cached:
            path, payload = json_cached
            if mongo_coll is not None:
                save_mongo_payload(mongo_coll, target, payload, args.prompt_version)
            print(f"JSON 캐시 사용: {target.corp_name} / {trade_date}")
            print_result(path, payload, from_cache=True)
            return

    client, keys = load_env()
    if args.no_llm:
        client = None

    mode = "근거 수집만" if args.no_llm else f"AI 요인 분석({LLM_MODEL})"
    print(f"새 분석 실행: {target.corp_name} / {trade_date} / {mode}")
    pack = build_evidence_pack(target, keys, report_date)

    if args.no_llm:
        payload = build_cached_payload(target, None, pack, args.prompt_version)
        saved_to = []
        if mongo_coll is not None:
            saved_to.append(save_mongo_payload(mongo_coll, target, payload, args.prompt_version))
        if args.storage in {"json", "both"}:
            saved_to.append(str(save_json_payload(args.output_dir, target, payload)))
        print_result(" / ".join(saved_to), payload, from_cache=False)
        return

    assert client is not None
    report = summarize_factors(client, target, pack)
    report["_prompt_version"] = args.prompt_version
    cost = estimate_openai_cost(report.get("_usage", {}))
    payload = build_cached_payload(target, report, pack, args.prompt_version, cost)
    saved_to = []
    if mongo_coll is not None:
        saved_to.append(save_mongo_payload(mongo_coll, target, payload, args.prompt_version))
    if args.storage in {"json", "both"}:
        saved_to.append(str(save_json_payload(args.output_dir, target, payload)))
    print_result(" / ".join(saved_to), payload, from_cache=False)


if __name__ == "__main__":
    main()
