"""LLM 브리핑 생성 클라이언트.

OpenAI Chat API 호출 + 프롬프트 조립 + 결과 파싱.

전제:
  - SYSTEM_PROMPT, USER_PROMPT_TEMPLATE 는 prompts/ 폴더에서 로드
  - TIER_INSTRUCTION 은 extraction 모듈에서 import
  - API 키는 config.OPENAI_API_KEY
"""
from __future__ import annotations

import json
import re
from typing import Optional

from openai import OpenAI

from .. import config as cfg
from .extraction import TIER_INSTRUCTION


# ─── 프롬프트 로드 (모듈 로드 시 한 번) ──────────────────────────────────────
SYSTEM_PROMPT        = (cfg.PROMPTS_DIR / "system_prompt.txt").read_text(encoding="utf-8")
USER_PROMPT_TEMPLATE = (cfg.PROMPTS_DIR / "user_prompt_template.txt").read_text(encoding="utf-8")


# ─── OpenAI 클라이언트 (지연 생성) ──────────────────────────────────────────
_client: Optional[OpenAI] = None

def _get_client() -> OpenAI:
    global _client
    if _client is None:
        if not cfg.OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY 미설정 — .env 확인 필요")
        _client = OpenAI(api_key=cfg.OPENAI_API_KEY)
    return _client


# ─── 브리핑 생성 ─────────────────────────────────────────────────────────────
def generate_brief(
    *,
    model: str,
    corp_name: str,
    stock_code: str,
    industry: str,
    gics_sector: str,
    business_report_text: str,
    mda_text: str = "",
    performance_context: str = "",
    price_factors_context: str = "",
    tier_instruction: str = "",
) -> Optional[dict]:
    """LLM 호출 → 브리핑 JSON 반환.

    Returns:
      성공: dict (brief 필드들 + _usage)
      실패: None
    """
    user_prompt = USER_PROMPT_TEMPLATE.format(
        corp_name             = corp_name,
        stock_code            = stock_code,
        industry              = industry,
        gics_sector           = gics_sector,
        business_report_text  = business_report_text or "데이터 없음",
        mda_text              = mda_text or "데이터 없음",
        performance_context   = performance_context or "해당 없음",
        price_factors_context = price_factors_context or "데이터 없음",
        tier_instruction      = tier_instruction or TIER_INSTRUCTION[4],
    )

    content = ""
    try:
        client = _get_client()
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": user_prompt},
            ],
            max_completion_tokens=8000,
        )

        msg   = response.choices[0].message
        usage = response.usage
        reasoning_tokens = getattr(
            getattr(usage, "completion_tokens_details", None),
            "reasoning_tokens", 0
        )
        output_tokens = usage.completion_tokens - reasoning_tokens

        content = msg.content or ""
        json_match = re.search(r"\{.*\}", content, re.DOTALL)
        if json_match:
            content = json_match.group()

        result = json.loads(content)
        result["_usage"] = {
            "prompt_tokens":     usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "reasoning_tokens":  reasoning_tokens,
            "output_tokens":     output_tokens,
        }
        return result

    except json.JSONDecodeError as e:
        print(f"    [ERROR] JSON 파싱 실패: {e}")
        return None
    except Exception as e:
        print(f"    [ERROR] API 호출 실패: {e}")
        return None


# ─── 결과 검증 ───────────────────────────────────────────────────────────────
def validate_brief(brief: dict) -> list[str]:
    """브리핑 구조 검증 → 경고 메시지 리스트."""
    warnings = []
    REQUIRED_KEYS = ["company_overview", "business_model", "main_customers",
                     "price_factors", "key_evidence", "confidence"]
    for key in REQUIRED_KEYS:
        if key not in brief:
            warnings.append(f"[MISSING] 필수 키 없음: {key}")
    if "price_factors" in brief:
        n = len(brief["price_factors"])
        if not (3 <= n <= 5):
            warnings.append(f"[RANGE] price_factors: {n}개 (허용: 3~5개)")
    if "confidence" in brief and brief["confidence"] not in {"high", "medium", "low"}:
        warnings.append(f"[VALUE] confidence 비허용값: '{brief['confidence']}'")

    # business_model 에 % 수치 포함 여부
    bm = brief.get("business_model", "")
    if bm and "%" not in bm:
        warnings.append("[QUALITY] business_model에 매출 비율(%)이 없음")
    return warnings


# ─── 비용 추적 ───────────────────────────────────────────────────────────────
class UsageTracker:
    """누적 토큰/비용 추적."""

    # 가격: per 1M tokens (USD)
    PRICES = {
        "gpt-5-mini":   {"input": 0.25, "output": 2.00},
        "gpt-5.4-mini": {"input": 0.75, "output": 4.50},
    }

    def __init__(self, model: str):
        self.model = model
        self.price = self.PRICES.get(model, {"input": 0.5, "output": 2.0})
        self.input_tokens     = 0
        self.output_tokens    = 0
        self.reasoning_tokens = 0
        self.cost_usd         = 0.0
        self.count            = 0

    def add(self, usage: dict):
        i = usage.get("input_tokens", 0) or usage.get("prompt_tokens", 0)
        o = usage.get("output_tokens", 0) or usage.get("completion_tokens", 0)
        r = usage.get("reasoning_tokens", 0)
        cost = i / 1_000_000 * self.price["input"] + o / 1_000_000 * self.price["output"]
        self.input_tokens     += i
        self.output_tokens    += o
        self.reasoning_tokens += r
        self.cost_usd         += cost
        self.count            += 1

    def summary(self) -> str:
        return (
            f"누적 {self.count:,}개  /  input {self.input_tokens:,} + "
            f"output {self.output_tokens:,} tokens  /  "
            f"${self.cost_usd:.4f} (~₩{self.cost_usd*1350:.0f})"
        )
