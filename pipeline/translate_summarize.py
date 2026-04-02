"""
Qwen3 4B - 격식체·일상체 번역 + 요약 단일 호출 파이프라인
한 번의 LLM 호출로 격식체 번역, 일상체 번역, 요약을 동시에 처리.

Setup:
  1. ollama pull qwen3:4b
  2. pip install ollama python-dotenv

Usage:
  python pipeline/translate_summarize.py
"""

import json
import sys
import ollama
from dotenv import load_dotenv
import os

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

load_dotenv()

MODEL = os.getenv("MODEL_NAME", "qwen3:4b")

SYSTEM_PROMPT = """You are a professional AI news translator and summarizer.
Given a news article, produce ALL three outputs at once:

1. **translation**: Translate the ENTIRE text into natural Korean.
2. **summary_formal**: Summarize in exactly {n} sentence(s) in formal Korean (격식체, ~습니다/~됩니다). Key points only.
3. **summary_casual**: Summarize in exactly {n} sentence(s) in casual Korean (일상체, ~해요/~예요/~거예요). Key points only.

Rules:
- Keep abbreviations like RAG, LLM, GPU, API, NPU in English.
- Transliterate technical terms: Fine-tuning→파인튜닝, Embedding→임베딩, Prompt→프롬프트.
- For new proper nouns, use: OriginalTerm(한국어, brief explanation) on first mention.
- Summaries must NOT copy translation word-for-word.
- Output ONLY valid JSON. No explanation, no preamble."""

PREFILL = '{"translation": "'


# ────────────────────────────────────────────────
# Core Function
# ────────────────────────────────────────────────
def translate_and_summarize(
    text: str,
    summary_sentences: int = 3,
    temperature: float = 0.3,
) -> dict:
    """
    영어 뉴스 기사를 격식체·일상체로 번역하고 요약합니다 (단일 LLM 호출).

    Args:
        text: 원본 영어 텍스트
        summary_sentences: 요약 문장 수 (기본: 3)
        temperature: 생성 다양성 (0.0~1.0)

    Returns:
        {
            "translation": str,     # 번역 전문
            "summary_formal": str,  # 격식체 3줄 요약
            "summary_casual": str,  # 일상체 3줄 요약
        }
    """
    system = SYSTEM_PROMPT.format(n=summary_sentences)

    response = ollama.chat(
        model=MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": text},
            {"role": "assistant", "content": PREFILL},
        ],
        options={
            "temperature": temperature,
            "num_predict": 3000,
            "num_gpu": 99,
        },
    )

    raw = PREFILL + response.message.content
    return _extract_json(raw)


def _extract_json(text: str) -> dict:
    """LLM 응답에서 첫 번째 완전한 JSON 객체를 추출합니다."""
    text = text.strip()

    if "</think>" in text:
        text = text.split("</think>")[-1].strip()

    start = text.find("{")
    if start != -1:
        try:
            obj, _ = json.JSONDecoder().raw_decode(text, start)
            return obj
        except json.JSONDecodeError:
            pass

    return {
        "translation": text,
        "summary_formal": "(파싱 실패)",
        "summary_casual": "(파싱 실패)",
    }


# ────────────────────────────────────────────────
# Batch Processing
# ────────────────────────────────────────────────
def batch_translate_summarize(
    texts: list,
    summary_sentences: int = 3,
) -> list:
    """여러 텍스트를 순서대로 번역+요약 처리합니다."""
    results = []
    for i, text in enumerate(texts, 1):
        print(f"[{i}/{len(texts)}] 처리 중...")
        try:
            result = translate_and_summarize(text, summary_sentences)
            results.append({"index": i, "status": "ok", **result})
        except Exception as e:
            results.append({"index": i, "status": "error", "error": str(e)})
    return results


# ────────────────────────────────────────────────
# CLI Demo
# ────────────────────────────────────────────────
def print_result(result: dict, label: str = "") -> None:
    sep = "=" * 60
    div = "-" * 60
    print(f"\n{sep}")
    if label:
        print(f"  {label}")
        print(sep)
    print("[원문 번역본]")
    print(result.get("translation", "(없음)"))
    print(div)
    print("[격식체 요약]")
    print(result.get("summary_formal", "(없음)"))
    print(div)
    print("[일상체 요약]")
    print(result.get("summary_casual", "(없음)"))
    print(sep)


if __name__ == "__main__":
    sample = """
    OpenAI has released GPT-4.1, its latest flagship model, featuring significant improvements
    in coding, instruction following, and long-context understanding. The model supports a
    1 million token context window and shows a 21% improvement on coding benchmarks compared
    to GPT-4o. OpenAI claims GPT-4.1 is particularly effective for agentic tasks, where AI
    systems autonomously complete multi-step workflows.
    """

    result = translate_and_summarize(text=sample, summary_sentences=3)
    print_result(result, "번역 + 요약 결과")
