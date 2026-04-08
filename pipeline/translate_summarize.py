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
  "translation": "<전체 한국어 번역>",
  "summary_formal": "<격식체 요약>",
  "summary_casual": "<일상체 요약>"
}}
All three fields are REQUIRED. Never leave any field empty.

━━━ TRANSLATION RULES ━━━
1. Translate the ENTIRE article into Korean.
2. Keep these abbreviations in English exactly as-is: RAG, LLM, GPU, NPU, API, RLHF, SFT, LoRA, QLoRA, P2P, B2B, SNS.
3. Standard tech transliterations (use exactly these):
   Fine-tuning→파인튜닝 / Embedding→임베딩 / Prompt→프롬프트 / Transformer→트랜스포머
   Startup→스타트업 / Platform→플랫폼 / Algorithm→알고리즘

4. PROPER NOUN FORMAT — applies ONLY to English/Western company names, product names, and brand names.
   • Rule: EnglishName(한국어 음차) on FIRST mention only. EnglishName alone after that.
   • Standard glossary (use exactly these Korean forms):
     Anthropic(앤트로픽) / OpenAI(오픈에이아이) / Google(구글) / Meta(메타) / Microsoft(마이크로소프트)
     Nvidia(엔비디아) / Apple(애플) / Amazon(아마존) / Samsung(삼성) / Intel(인텔)
     ChatGPT(챗GPT) / Gemini(제미나이) / Llama(라마) / Grok(그록) / Copilot(코파일럿)
     Huawei(화웨이) / Xiaomi(샤오미) / Tencent(텐센트) / Alibaba(알리바바) / ByteDance(바이트댄스)
     Tesla(테슬라) / SpaceX(스페이스X) / DeepMind(딥마인드) / xAI(xAI)
   • For names NOT in the glossary: use the most widely recognized Korean transliteration.

5. DO NOT apply the English(한국어) format to:
   • Korean person names (홍길동, 이재용 etc.) — write in Korean only, no parentheses
   • Korean company/institution names (삼성전자, 국가정보원, 한국철도공사 etc.) — Korean only
   • Already-Korean loanwords (디즈니, 마그네틱, 인터넷 etc.) — no duplication

6. New English coinages not in the glossary: EnglishTerm(한국어 음차, 한 줄 설명) on first mention.
   Example: Blackwell Ultra(블랙웰 울트라, Nvidia 차세대 GPU 아키텍처)

━━━ SUMMARY RULES ━━━
- summary_formal: exactly {n} Korean sentence(s), 격식체 (~습니다/~됩니다). Must be complete.
- summary_casual: exactly {n} Korean sentence(s), 일상체 (~해요/~예요/~거예요). Must be complete.
- Summaries must NOT copy translation sentences verbatim — paraphrase.
- Apply all language and proper noun rules above."""


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
    summary_sentences: int = 3,
    temperature: float = 0.1,
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

    for attempt in range(3):   # 최대 3회 시도
        response = ollama.chat(
            model=MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": text},
            ],
            options={
                "temperature": 0.1,
                "num_predict": -1,   # 무제한 — EOS 토큰까지 생성
                "num_gpu": 99,
            },
            think=False,  # thinking 모드 비활성화 (qwen3.5:4b 전용)
        )
        result = _extract_json(response.message.content)
        if "(파싱 실패)" not in result.get("summary_formal", ""):
            return result

    return result  # 3회 실패 시 마지막 결과 반환


def _extract_json(text: str) -> dict:
    """pipeline.utils.extract_json 위임 (하위 호환용 래퍼)"""
    return _extract_json_util(text)


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
