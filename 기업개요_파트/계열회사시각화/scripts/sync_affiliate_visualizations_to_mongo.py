from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


def find_project_root(start: Path) -> Path:
    for path in (start, *start.parents):
        if (path / "RAG").exists() or (path / "output" / "affiliate_visualization").exists():
            return path
    return start


ROOT = find_project_root(Path(__file__).resolve().parents[1])
DEFAULT_MANIFEST = ROOT / "output" / "affiliate_visualization" / "_manifest.json"
DEFAULT_DB_NAME = "filmn9"
DEFAULT_COLLECTION_NAME = "affiliate_visualizations"


def configure_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass


def load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(ROOT / ".env")


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"manifest not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        manifest = json.load(f)
    if not isinstance(manifest.get("records"), list):
        raise ValueError("manifest records field is missing or invalid")
    return manifest


def derive_report_year(record: dict[str, Any]) -> int | None:
    report_kind = str(record.get("report_kind", ""))
    match = re.search(r"(20\d{2})", report_kind)
    if match:
        return int(match.group(1))

    rcept_dt = str(record.get("rcept_dt", ""))
    if len(rcept_dt) >= 4 and rcept_dt[:4].isdigit():
        return int(rcept_dt[:4])
    return None


def make_document_key(record: dict[str, Any]) -> str:
    stock_code = str(record.get("stock_code", ""))
    report_kind = str(record.get("report_kind", ""))
    rcept_no = str(record.get("rcept_no", ""))
    return f"{stock_code}:{report_kind}:{rcept_no}"


def asset_kind(source_type: str) -> str:
    if source_type == "original_dart_image":
        return "original_image"
    if source_type.startswith("generated_"):
        return "generated_svg"
    return "none"


def apply_asset_base_url(record: dict[str, Any], asset_base_url: str | None) -> None:
    if not asset_base_url or not record.get("visual_path"):
        return

    rel_path = str(record["visual_path"]).replace("\\", "/")
    marker = "output/affiliate_visualization/"
    if marker in rel_path:
        rel_path = rel_path.split(marker, 1)[1]
    record["visual_url"] = asset_base_url.rstrip("/") + "/" + rel_path.lstrip("/")


def normalize_record(record: dict[str, Any], manifest: dict[str, Any], asset_base_url: str | None) -> dict[str, Any]:
    doc = dict(record)
    source_type = str(doc.get("source_type", ""))
    apply_asset_base_url(doc, asset_base_url)

    doc["document_key"] = make_document_key(doc)
    doc["report_year"] = derive_report_year(doc)
    doc["has_visual"] = bool(doc.get("visual_path"))
    doc["asset_kind"] = asset_kind(source_type)
    doc["status"] = "insufficient_data" if source_type == "insufficient_data" else "success"
    doc["manifest_generated_at"] = manifest.get("generated_at", "")
    doc["synced_at"] = now_iso()
    return doc


def select_records(records: list[dict[str, Any]], stock_code: str | None, limit: int | None) -> list[dict[str, Any]]:
    selected = records
    if stock_code:
        selected = [record for record in selected if str(record.get("stock_code", "")) == stock_code]
    if limit is not None:
        selected = selected[:limit]
    return selected


def get_collection(args: argparse.Namespace):
    uri = args.mongo_uri or os.getenv("MONGO_URI")
    if not uri:
        raise RuntimeError("MONGO_URI is not set. Add it to .env or pass --mongo-uri.")

    try:
        from pymongo import MongoClient
    except ImportError as exc:
        raise RuntimeError("pymongo is required. Install it with: pip install pymongo") from exc

    mongo_kwargs: dict[str, Any] = {"serverSelectionTimeoutMS": args.timeout_ms}
    use_certifi = args.use_certifi
    if use_certifi is None:
        uri_lower = uri.lower()
        use_certifi = uri_lower.startswith("mongodb+srv://") or "tls=true" in uri_lower or "ssl=true" in uri_lower

    if use_certifi:
        try:
            import certifi
        except ImportError as exc:
            raise RuntimeError("certifi is required when --use-certifi is enabled.") from exc
        mongo_kwargs["tlsCAFile"] = certifi.where()

    client = MongoClient(uri, **mongo_kwargs)
    client.admin.command("ping")
    return client[args.db][args.collection]


def ensure_indexes(collection) -> None:
    collection.create_index(
        [("stock_code", 1), ("report_kind", 1), ("rcept_no", 1)],
        unique=True,
        name="stock_report_receipt_unique",
    )
    collection.create_index("stock_code", name="stock_code_idx")
    collection.create_index("source_type", name="source_type_idx")
    collection.create_index("has_original_image", name="has_original_image_idx")
    collection.create_index("report_year", name="report_year_idx")


def print_summary(manifest: dict[str, Any], docs: list[dict[str, Any]], manifest_path: Path) -> None:
    print(f"manifest: {manifest_path}")
    print(f"manifest_records: {manifest.get('total_records', len(manifest.get('records', [])))}")
    print(f"selected_records: {len(docs)}")
    print("source_type_counts:")
    for source_type, count in manifest.get("source_type_counts", {}).items():
        print(f"  {source_type}: {count}")
    print("sample_keys:")
    for doc in docs[:5]:
        print(f"  {doc['document_key']} -> {doc.get('source_type', '')}")


def dry_run(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest)
    manifest = load_manifest(manifest_path)
    records = select_records(manifest["records"], args.stock_code, args.limit)
    docs = [normalize_record(record, manifest, args.asset_base_url) for record in records]
    print("[DRY RUN] MongoDB write skipped")
    print_summary(manifest, docs, manifest_path)
    return 0


def upload(args: argparse.Namespace) -> int:
    try:
        from pymongo import UpdateOne
    except ImportError as exc:
        raise RuntimeError("pymongo is required. Install it with: pip install pymongo") from exc

    manifest_path = Path(args.manifest)
    manifest = load_manifest(manifest_path)
    records = select_records(manifest["records"], args.stock_code, args.limit)
    docs = [normalize_record(record, manifest, args.asset_base_url) for record in records]
    print_summary(manifest, docs, manifest_path)

    collection = get_collection(args)
    if not args.skip_indexes:
        ensure_indexes(collection)

    total_upserted = 0
    total_modified = 0
    total_matched = 0
    batch_size = max(args.batch_size, 1)

    for start in range(0, len(docs), batch_size):
        batch = docs[start : start + batch_size]
        ops = []
        for doc in batch:
            key_filter = {
                "stock_code": doc["stock_code"],
                "report_kind": doc.get("report_kind", ""),
                "rcept_no": doc.get("rcept_no", ""),
            }
            ops.append(
                UpdateOne(
                    key_filter,
                    {
                        "$set": doc,
                        "$setOnInsert": {"db_created_at": now_iso()},
                    },
                    upsert=True,
                )
            )

        result = collection.bulk_write(ops, ordered=False)
        total_upserted += len(result.upserted_ids)
        total_modified += result.modified_count
        total_matched += result.matched_count
        print(
            f"progress {min(start + batch_size, len(docs))}/{len(docs)} "
            f"(upserted={total_upserted}, matched={total_matched}, modified={total_modified})"
        )

    print("done")
    print(f"db: {args.db}.{args.collection}")
    print(f"upserted: {total_upserted}")
    print(f"matched: {total_matched}")
    print(f"modified: {total_modified}")
    return 0


def find_one(args: argparse.Namespace) -> int:
    if not args.stock_code:
        raise RuntimeError("--find requires --stock-code")
    collection = get_collection(args)
    doc = collection.find_one({"stock_code": args.stock_code}, {"_id": 0})
    if not doc:
        print(f"not_found: {args.stock_code}")
        return 1
    print(json.dumps(doc, ensure_ascii=False, indent=2))
    return 0


def parse_args() -> argparse.Namespace:
    load_env()
    parser = argparse.ArgumentParser(description="Sync affiliate visualization manifest records to MongoDB.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST), help="Path to _manifest.json")
    parser.add_argument("--mongo-uri", default=None, help="MongoDB URI. Defaults to MONGO_URI from .env.")
    parser.add_argument("--db", default=os.getenv("MONGO_DB", DEFAULT_DB_NAME), help="MongoDB database name")
    parser.add_argument(
        "--collection",
        default=os.getenv("AFFILIATE_VISUAL_COLLECTION", DEFAULT_COLLECTION_NAME),
        help="MongoDB collection name",
    )
    parser.add_argument("--asset-base-url", default=None, help="Override visual_url with this public asset base URL")
    parser.add_argument("--stock-code", default=None, help="Sync or find only one stock code")
    parser.add_argument("--limit", type=int, default=None, help="Sync only the first N selected records")
    parser.add_argument("--batch-size", type=int, default=200, help="MongoDB bulk_write batch size")
    parser.add_argument("--timeout-ms", type=int, default=10000, help="MongoDB server selection timeout")
    parser.add_argument("--dry-run", action="store_true", help="Read and normalize records without writing MongoDB")
    parser.add_argument("--find", action="store_true", help="Find one document by --stock-code")
    parser.add_argument("--skip-indexes", action="store_true", help="Skip index creation")
    parser.add_argument("--use-certifi", dest="use_certifi", action="store_true", default=None, help="Use certifi CA bundle for TLS")
    parser.add_argument("--no-certifi", dest="use_certifi", action="store_false", help="Do not pass certifi tlsCAFile")
    return parser.parse_args()


def main() -> int:
    configure_stdout()
    args = parse_args()
    if args.find:
        return find_one(args)
    if args.dry_run:
        return dry_run(args)
    return upload(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"error: {type(exc).__name__}: {exc}")
        raise SystemExit(1)
