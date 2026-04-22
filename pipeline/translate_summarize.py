"""
Qwen3.5 4B - 격식체·일상체 번역 + 요약 단일 호출 파이프라인
한 번의 LLM 호출로 격식체 번역, 일상체 번역, 요약을 동시에 처리.

Setup:
  1. ollama pull qwen3.5:4b
  2. pip install ollama python-dotenv

Usage:
  python pipeline/translate_summarize.py
"""

import re
import sys
import ollama
from dotenv import load_dotenv
import os
from pipeline.utils import preprocess_text, extract_json as _extract_json_util

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

load_dotenv()

MODEL = os.getenv("MODEL_NAME", "qwen3.5:4b")

SYSTEM_PROMPT = """You are a professional Korean translator and summarizer.

━━━ RULE 0: OUTPUT LANGUAGE (ABSOLUTE PRIORITY) ━━━
Output MUST contain ONLY Korean (한글) + Latin (A-Z/a-z) + digits + punctuation.
ZERO TOLERANCE — even one character from the following scripts causes failure:
  • Chinese/Hanzi (漢字): including 去, 年, 的, 在 etc.
  • Cyrillic/Russian: А, Б, В … я etc.
  • Thai, Arabic, Hebrew, Japanese kana
If the source contains these scripts, translate or romanize them into Korean. NEVER copy them.

━━━ OUTPUT FORMAT ━━━
Return ONLY valid JSON. No markdown fences, no explanation outside JSON.
{{
  "title_ko": "<한국어 제목>",
  "translation": "<전체 한국어 번역>",
  "summary_formal": "<격식체 요약>",
  "summary_casual": "<일상체 요약>"
}}
All four fields are REQUIRED. Never leave any field empty.
If no title is provided, set "title_ko" to "".

━━━ TRANSLATION RULES ━━━
1. Translate the ENTIRE article into Korean.
   Use journalistic body style (~했다 / ~밝혔다 / ~에 따르면). Prefer active voice: '발표했다' over '발표됐다'.
2. Keep these abbreviations in English exactly as-is: RAG, LLM, GPU, NPU, API, RLHF, SFT, LoRA, QLoRA, P2P, B2B, SNS.
3. AI/tech terms must stay in English — do NOT transliterate:
   Fine-tuning, Embedding, Prompt, Transformer, Benchmark, Inference, Token, Dataset, Checkpoint
   General loanwords already standard in Korean are fine: Startup→스타트업, Platform→플랫폼, Algorithm→알고리즘

4. PROPER NOUNS — company names, product names, brand names must stay in English. No Korean transliteration.
   • Rule: English name ONLY — do NOT add Korean phonetic transcription in parentheses.
   • e.g., Anthropic (NOT 앤트로픽), OpenAI (NOT 오픈에이아이), Nvidia (NOT 엔비디아),
     Google (NOT 구글), Meta (NOT 메타), Microsoft (NOT 마이크로소프트),
     Gemini (NOT 제미나이), Llama (NOT 라마), Claude (NOT 클로드), ChatGPT (NOT 챗GPT)
   • Model version numbers always stay in English: e.g., GPT-4o, Claude 3.5 Sonnet, Llama 3.1 70B

5. PERSON NAMES — use English name only. Do NOT add Korean transliteration.
   • e.g., Sam Altman (NOT 샘 올트먼), Jensen Huang (NOT 젠슨 황), Elon Musk (NOT 일론 머스크)
   • Job titles are translated into Korean: professor→교수, researcher→연구원, founder→창업자

6. NUMBERS AND UNITS
   • Currency symbols: $ → 달러 / € → 유로 / £ → 파운드 / ¥ → 엔 (중국 화폐는 위안)
     Exact figures may include original: 25억 달러($2.5B)
   • T / trillion → 조: $1T → 1조 달러
   • B / billion  → 억: $2.5B → 25억 달러
   • M / million  → 만: $500M → 5억 달러
   • K / thousand → 천: 5K → 5천 (context permitting)
   • Unit context — always specify the unit: parameters→개, people→명, tokens→개
     e.g., 70B parameters → 700억 개 파라미터
   • Multipliers: 2x → 2배 / 3x → 3배
   • Technical units (GB, TB, ms, TFLOPS, %) — keep as-is

7. Korean-origin names: write in Korean only, no parenthetical annotation.
   • Korean person names: 홍길동, 이재용 etc.
   • Korean company/institution names: 삼성전자, 국가정보원 etc.

8. Brand-new English coinages with no established Korean equivalent: EnglishTerm(한 줄 설명) on first mention.
   Example: Blackwell Ultra(Nvidia 차세대 GPU 아키텍처) — explanation in Korean, but NO Korean phonetic transcription.

━━━ TITLE TRANSLATION RULES ━━━
- title_ko: translate the English title into Korean headline style.
- Use noun-final endings: ~함 / ~됨 / ~발표 / ~출시 / ~공개
- Keep it concise — omit articles (a/the) and filler words.
- Apply all proper noun, person name, and number rules above.
- If no title is given in the input, set title_ko to "".

━━━ SUMMARY RULES ━━━
- summary_formal: exactly {n} Korean sentence(s), 격식체 (~습니다/~됩니다). Must be complete.
- summary_casual: exactly {n} Korean sentence(s), 일상체 (~해요/~예요/~거예요). Must be complete.
- Summaries must NOT copy translation sentences verbatim — paraphrase with different expressions.
- Use journalistic style (~했다/~밝혔다). Prefer active voice: '발표했다' over '발표됐다'.
- Apply all language, proper noun, and number rules above."""


# ────────────────────────────────────────────────
# Summary-Only Prompt (번역 토큰 초과 시 별도 호출용)
# SYSTEM_PROMPT보다 훨씬 짧게 유지 — 토큰 예산 여유 확보가 목적
# ────────────────────────────────────────────────
SUMMARY_ONLY_PROMPT = (
    "Korean summarizer. Return ONLY valid JSON, no markdown:\n"
    '{{"summary_formal":"<{n} sentence(s), ~습니다/됩니다 style>","summary_casual":"<{n} sentence(s), ~해요/거예요 style>"}}\n'
    "Rules: Korean only. Both fields required. No empty values."
)

# 요약 전용 호출에서 번역문 입력 최대 길이 (토큰 예산 보호)
_SUMMARY_INPUT_MAX = 2500


# ────────────────────────────────────────────────
# Sentence Estimator
# ────────────────────────────────────────────────
def estimate_sentences(text: str, max_sentences: int = 3) -> int:
    """
    원문 문장 수를 추정해 summary_sentences 상한을 반환합니다.

    약어(A.I., G.P.T.) · URL · 소수점의 마침표 오탐을 줄이기 위해
    '2글자 이상 단어 뒤의 문장 종결 부호(.!?) + 공백' 패턴만 카운트합니다.

    Returns:
        min(추정 문장 수, max_sentences)
        — 원문보다 많은 줄을 요약하도록 강제하지 않기 위해 상한을 둠.
    """
    parts = re.split(r'(?<=[a-zA-Z]{2})[.!?]\s+', text.strip())
    return min(max(1, len(parts)), max_sentences)


# ────────────────────────────────────────────────
# Core Function
# ────────────────────────────────────────────────
def translate_and_summarize(
    text: str,
    title: str = "",
    summary_sentences: int = 3,
    temperature: float = 0.1,
) -> dict:
    """
    영어 뉴스 기사를 격식체·일상체로 번역하고 요약합니다 (단일 LLM 호출).

    Args:
        text: 원본 영어 본문
        title: 영어 기사 제목 (선택). 제공 시 title_ko 번역 포함.
        summary_sentences: 요약 문장 수 (기본: 3)
        temperature: 생성 다양성 (0.0~1.0)

    Returns:
        {
            "title_ko":      str,  # 한국어 제목 (title 미제공 시 "")
            "translation":   str,  # 번역 전문
            "summary_formal": str, # 격식체 요약
            "summary_casual": str, # 일상체 요약
        }
    """
    system = SYSTEM_PROMPT.format(n=summary_sentences)
    user_content = f"[TITLE]\n{title}\n\n[BODY]\n{text}" if title else text

    for attempt in range(3):   # 최대 3회 시도
        response = ollama.chat(
            model=MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            options={
                "temperature":    0.1,
                "num_predict":    -1,    # 무제한 — EOS까지 생성 (repeat_penalty로 루프 방지)
                "num_ctx":        12288, # 8192→12288: 장문(6000자+) 번역 후 요약 공간 확보
                "num_gpu":        99,
                "repeat_penalty": 1.15,  # 반복 토큰 루프 방지 (id=132 재발 방지)
            },
            think=False,  # thinking 모드 비활성화 (qwen3.5:4b 전용)
        )
        result = _extract_json(response.message.content)
        if result.get("summary_formal") and "(파싱 실패)" not in result["summary_formal"]:
            return result

    # ── 번역은 됐는데 summary만 잘린 경우 → summary-only 재호출 ──────────
    # SYSTEM_PROMPT가 길어서 장문 번역 후 토큰 예산이 소진될 때 발생.
    # 번역문을 입력으로 주는 짧은 프롬프트로 summary만 별도 생성.
    if result.get("translation"):
        summary = _retry_summary_only(result["translation"], summary_sentences)
        result["summary_formal"] = summary.get("summary_formal", "")
        result["summary_casual"] = summary.get("summary_casual", "")

    return result


def _extract_json(text: str) -> dict:
    """pipeline.utils.extract_json 위임 (하위 호환용 래퍼)"""
    return _extract_json_util(text)


def _retry_summary_only(translation: str, n: int) -> dict:
    """
    번역은 성공했지만 summary 필드가 잘린 경우 summary만 별도 호출.

    SYSTEM_PROMPT 대신 SUMMARY_ONLY_PROMPT(매우 짧음)를 사용해
    토큰 예산을 summary 생성에만 집중.
    """
    prompt = SUMMARY_ONLY_PROMPT.format(n=n)
    # 번역문이 길면 앞부분만 사용 (핵심은 초반에 집중)
    ko_input = translation[:_SUMMARY_INPUT_MAX]

    for _ in range(2):
        try:
            response = ollama.chat(
                model=MODEL,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user",   "content": ko_input},
                ],
                options={
                    "temperature": 0.1,
                    "num_predict": 600,   # summary 2필드만 생성 — 짧게 제한
                    "num_ctx":     4096,
                    "num_gpu":     99,
                },
                think=False,
            )
            raw = _extract_json_util(response.message.content)
            # summary_formal / summary_casual 만 반환 (translation 덮어쓰기 방지)
            if raw.get("summary_formal"):
                return {
                    "summary_formal": raw.get("summary_formal", ""),
                    "summary_casual": raw.get("summary_casual", ""),
                }
        except Exception:
            pass

    return {"summary_formal": "", "summary_casual": ""}


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
