"""
G-Eval — 요약 품질 자동 평가 (GPT-4o via OpenRouter)
평가 3축: 충실성 / 유창성 / 간결성 (각 5점 척도)
대상: summary_formal (격식체)

목표: G-Eval 3축 평균 ≥ 4.0 / 5.0

설치:
    pip install openai
환경변수:
    OPENROUTER_API_KEY
"""

import os
import json
import time
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
EVAL_MODEL = "openai/gpt-4o"

# ── G-Eval 프롬프트 (격식체) ──────────────────────
GEVAL_SYSTEM = """당신은 AI 뉴스 요약 품질을 평가하는 전문 평가자입니다.
아래 기준에 따라 요약문을 5점 척도로 평가하고, 반드시 JSON 형식으로만 응답하세요."""

GEVAL_USER_TEMPLATE = """[원문 (영어)]
{source}

[요약문 (한국어 격식체)]
{summary}

위 요약문을 아래 3가지 기준으로 각각 1~5점으로 평가하세요.

1. 충실성 (Faithfulness): 원문 내용을 벗어난 정보나 왜곡이 없는가?
   - 5: 원문 내용을 완전히 충실히 반영
   - 3: 일부 정보 누락 또는 경미한 왜곡
   - 1: 원문과 다른 내용이 포함되거나 심각한 왜곡

2. 유창성 (Fluency): 문장이 자연스럽고 읽기 편한 한국어 격식체인가?
   - 5: 매우 자연스럽고 격식 있는 뉴스 문체
   - 3: 어색한 표현이 일부 있으나 전달은 됨
   - 1: 부자연스럽거나 격식체가 유지되지 않음

3. 간결성 (Conciseness): 핵심만 담고 불필요한 반복이나 군더더기가 없는가?
   - 5: 핵심만 간결하게 정리, 반복 없음
   - 3: 일부 불필요한 내용이나 반복 있음
   - 1: 심각한 반복 또는 핵심과 무관한 내용 포함

반드시 아래 JSON 형식으로만 응답하세요:
{{"faithfulness": <1-5>, "fluency": <1-5>, "conciseness": <1-5>}}"""


def geval_single(source: str, summary: str, retries: int = 3) -> dict:
    """
    단일 요약문 G-Eval 채점.

    Args:
        source  : 영어 원문
        summary : 한국어 격식체 요약 출력
        retries : API 실패 시 재시도 횟수

    Returns:
        {
            "faithfulness": int,   # 1~5
            "fluency":      int,
            "conciseness":  int,
            "average":      float,
            "raw":          str,   # GPT-4o 원본 응답
        }
    """
    try:
        from openai import OpenAI
    except ImportError:
        raise ImportError("pip install openai")

    if not OPENROUTER_API_KEY:
        raise ValueError("OPENROUTER_API_KEY 환경변수를 설정하세요.")

    client = OpenAI(api_key=OPENROUTER_API_KEY, base_url=OPENROUTER_BASE_URL)

    user_msg = GEVAL_USER_TEMPLATE.format(source=source[:2000], summary=summary)

    for attempt in range(retries):
        try:
            response = client.chat.completions.create(
                model=EVAL_MODEL,
                messages=[
                    {"role": "system", "content": GEVAL_SYSTEM},
                    {"role": "user",   "content": user_msg},
                ],
                temperature=0.0,
                max_tokens=100,
            )
            raw = response.choices[0].message.content.strip()
            scores = json.loads(raw)

            f = int(scores.get("faithfulness", 0))
            fl = int(scores.get("fluency", 0))
            c = int(scores.get("conciseness", 0))
            avg = round((f + fl + c) / 3, 2)

            return {
                "faithfulness": f,
                "fluency":      fl,
                "conciseness":  c,
                "average":      avg,
                "raw":          raw,
            }

        except (json.JSONDecodeError, KeyError):
            # JSON 파싱 실패 시 재시도
            if attempt < retries - 1:
                time.sleep(2)
            else:
                return {
                    "faithfulness": 0,
                    "fluency":      0,
                    "conciseness":  0,
                    "average":      0.0,
                    "raw":          raw if "raw" in locals() else "parse error",
                }
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(3)
            else:
                return {
                    "faithfulness": 0,
                    "fluency":      0,
                    "conciseness":  0,
                    "average":      0.0,
                    "raw":          f"error: {e}",
                }


def batch_geval(
    sources: list[str],
    summaries: list[str],
    delay: float = 0.5,
) -> dict:
    """
    여러 요약문 G-Eval 배치 채점.

    Args:
        sources   : 영어 원문 리스트
        summaries : 한국어 격식체 요약 리스트
        delay     : API 호출 간 딜레이(초) — Rate Limit 방지

    Returns:
        {
            "faithfulness_mean": float,
            "fluency_mean":      float,
            "conciseness_mean":  float,
            "average_mean":      float,
            "scores":            list[dict],
        }
    """
    results = []
    for i, (src, summ) in enumerate(zip(sources, summaries), 1):
        print(f"  G-Eval [{i}/{len(sources)}] 채점 중...")
        result = geval_single(src, summ)
        results.append(result)
        time.sleep(delay)

    def mean(key):
        vals = [r[key] for r in results if r[key] > 0]
        return round(sum(vals) / len(vals), 2) if vals else 0.0

    return {
        "faithfulness_mean": mean("faithfulness"),
        "fluency_mean":      mean("fluency"),
        "conciseness_mean":  mean("conciseness"),
        "average_mean":      mean("average"),
        "scores":            results,
    }
