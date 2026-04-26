"""
test_fallback.py — OpenRouter fallback 테스트

케이스 1: gemini_client=None → 즉시 OpenRouter 경로 (직접 테스트)
케이스 2: 잘못된 Gemini 키 → 에러 감지 → OpenRouter fallback (실제 fallback 흐름)
케이스 3: 전체 파이프라인 — Step 3까지 도달하는 VentureBeat 케이스를 bad Gemini키로 실행

실행:
    python test_fallback.py
"""

import os
import sys
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

import logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

from fact_checker.llm_client import call_with_fallback

SYSTEM = "You are a fact-checker. Reply in JSON only."
USER   = 'Does NVIDIA make GPUs? Reply: {"answer": "yes" or "no", "confidence": 0.99}'

SEP = "─" * 55


def test_direct_openrouter():
    """케이스 1: gemini_client=None → OpenRouter 직행"""
    print(f"\n{SEP}")
    print("케이스 1: gemini_client=None → OpenRouter 직행")
    print(SEP)

    text, used_fallback = call_with_fallback(
        system=SYSTEM,
        user=USER,
        gemini_client=None,
        temperature=0.0,
        max_tokens=64,
    )
    print(f"  used_fallback : {used_fallback}  ← True이어야 함")
    print(f"  응답          : {text[:120]}")
    assert used_fallback is True, "❌ fallback이 작동하지 않음"
    print("  ✅ PASS")


def test_bad_gemini_key_fallback():
    """케이스 2: 잘못된 Gemini 키 → 에러 감지 → OpenRouter fallback"""
    print(f"\n{SEP}")
    print("케이스 2: 잘못된 Gemini 키 → OpenRouter fallback")
    print(SEP)

    try:
        from google import genai
        bad_client = genai.Client(api_key="INVALID_KEY_FOR_TEST")
    except Exception as e:
        print(f"  google-genai 미설치 또는 Client 생성 실패: {e}")
        print("  → 케이스 1과 동일하므로 skip")
        return

    text, used_fallback = call_with_fallback(
        system=SYSTEM,
        user=USER,
        gemini_client=bad_client,
        temperature=0.0,
        max_tokens=64,
    )
    print(f"  used_fallback : {used_fallback}  ← True이어야 함")
    print(f"  응답          : {text[:120]}")
    assert used_fallback is True, "❌ 잘못된 키에서 fallback이 작동하지 않음"
    print("  ✅ PASS")


def test_pipeline_step3_with_bad_gemini():
    """케이스 3: 전체 파이프라인 — VentureBeat 케이스(Step 3 도달) + Gemini 키 무효화"""
    print(f"\n{SEP}")
    print("케이스 3: 파이프라인 Step 3 → OpenRouter fallback 경유")
    print(SEP)

    # Gemini 키를 임시로 무효화
    original_key = os.environ.get("GEMINI_API_KEY")
    os.environ["GEMINI_API_KEY"] = "INVALID_KEY_FOR_TEST"

    try:
        from fact_checker.pipeline import run_fact_check

        result = run_fact_check(
            title   = "Meta Releases Llama 4 Scout with 17B Parameters",
            content = (
                "Meta AI has officially released Llama 4 Scout, a 17 billion parameter "
                "model designed for efficient inference. The model achieves state-of-the-art "
                "results on multiple benchmarks including MMLU and HumanEval. "
                "The weights are available on Hugging Face under the Llama 4 license."
            ),
            source      = "VentureBeat AI",
            source_type = "media",
            skip_fc_api = True,   # Google FC API 키 없으므로 skip
            skip_llm    = False,
        )

        print(f"  fact_label         : {result.fact_label}")
        print(f"  confidence         : {result.confidence:.2f}")
        print(f"  step_reached       : {result.step_reached}")
        print(f"  verification_method: {result.verification_method}")
        print(f"  reasoning (앞 100자): {result.reasoning_trace[:100]}")

        assert result.fact_label in ("FACT", "RUMOR", "UNVERIFIED"), \
            f"❌ 예상치 못한 fact_label: {result.fact_label}"
        assert result.step_reached == 3, \
            f"❌ Step 3에 도달해야 함 (현재: {result.step_reached})"
        print("  ✅ PASS — OpenRouter fallback 경유로 Step 3 완료")

    finally:
        # 키 복원
        if original_key:
            os.environ["GEMINI_API_KEY"] = original_key
        else:
            del os.environ["GEMINI_API_KEY"]


if __name__ == "__main__":
    print("=" * 55)
    print("  OpenRouter Fallback 테스트")
    print("=" * 55)

    try:
        test_direct_openrouter()
    except AssertionError as e:
        print(f"  {e}")

    try:
        test_bad_gemini_key_fallback()
    except AssertionError as e:
        print(f"  {e}")

    try:
        test_pipeline_step3_with_bad_gemini()
    except AssertionError as e:
        print(f"  {e}")

    print(f"\n{'=' * 55}")
    print("  테스트 완료")
    print("=" * 55)
