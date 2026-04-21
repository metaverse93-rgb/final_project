"""
G-Eval — 요약 품질 자동 평가 (OpenRouter gpt-4.1-mini, logprobs 방식)
평가 4축: Consistency / Fluency / Coherence / Relevance (각 1~5 연속형)
대상: summary_formal (격식체)

논문 근거: Liu et al. (2023) "G-Eval: NLG Evaluation using GPT-4 with Better Human Alignment"
          Fabbri et al. (2021) "SummEval: Re-evaluating Summarization Evaluation"

점수 산출 (logprobs 가중평균 — 논문 원본 방식):
    각 축 점수 = Σ(i × P("i")) / Σ P("i")   (i ∈ {1,2,3,4,5})
    g_eval_score    = (consistency + fluency + coherence + relevance) / 4
    g_eval_weighted = consistency*0.4 + relevance*0.3 + fluency*0.2 + coherence*0.1

변경 이력:
    v1: Claude Haiku, JSON 정수 출력, source[:2000]
    v2: gpt-4.1-mini via OpenRouter, logprobs 연속형 점수, source[:10000]

환경변수:
    OPENROUTER_API_KEY
"""

import os
import math
import time
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
EVAL_MODEL = "openai/gpt-4.1-mini"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

GEVAL_SYSTEM = "You are a strict and impartial evaluator for Korean AI/tech news summaries."

# 각 축별 독립 프롬프트 — logprobs 방식은 축마다 별도 호출해서 점수 토큰 확률을 정확하게 추출
_CRITERION_TEMPLATES = {
    "consistency": """Evaluate the CONSISTENCY of the generated Korean summary against the source article.

INPUTS:
[A] Source Article (English):
{source}

[C] Generated Summary (Korean):
{generated_summary}

CRITERION — Consistency (일치성)
Compare [C] vs [A] ONLY.
Question: Are all facts in the generated summary consistent with the source article?

Scoring rubric:
5 — All facts consistent; nothing hallucinated, added, or distorted
4 — No factual errors; at most one minor fact omitted
3 — One fact slightly distorted OR one important fact missing
2 — Two or more factual errors OR significant distortion of the main claim
1 — Contains hallucinated facts OR directly contradicts the source

Think step by step, then output ONLY a single integer (1, 2, 3, 4, or 5). No other text.
Score:""",

    "fluency": """Evaluate the FLUENCY of the generated Korean summary.

INPUTS:
[C] Generated Summary (Korean):
{generated_summary}

CRITERION — Fluency (유창성)
Compare [C] ONLY. Do NOT use the source article.
Question: Is the Korean natural and easy to read for a Korean tech news audience?

Terminology rules (guide v2):
- Abbreviations (RAG, LLM, GPU, NPU, API, RLHF, SFT, LoRA, QLoRA) → English ONLY, no transliteration
- AI/tech terms (Fine-tuning, Embedding, Prompt, Transformer, Benchmark, Inference, Token, Dataset) → English ONLY
- Proper nouns (Nvidia, OpenAI, Anthropic, Sam Altman) → English ONLY, no Korean transliteration
- Currency: $ → 달러, $2.5B → 25억 달러
- Model versions: GPT-4o, Claude 3.5 Sonnet → English as-is
Violations: each -1 point

Scoring rubric:
5 — Reads like native Korean tech journalism; all terminology correctly formatted
4 — Mostly natural; at most 1 minor awkward phrase OR 1 terminology error
3 — Readable but noticeably unnatural phrasing OR 2 terminology errors
2 — Difficult to read due to awkward Korean OR systematic terminology errors
1 — Unreadable; machine-translated feel throughout

Think step by step, then output ONLY a single integer (1, 2, 3, 4, or 5). No other text.
Score:""",

    "coherence": """Evaluate the COHERENCE of the generated Korean summary.

INPUTS:
[C] Generated Summary (Korean):
{generated_summary}

CRITERION — Coherence (일관성)
Compare [C] ONLY.
Question: Is the generated summary logically structured and coherent?

Scoring rubric:
5 — Well-structured; sentences flow naturally and connect logically
4 — Mostly coherent; at most one slightly awkward transition
3 — Generally readable but with noticeable disorganization or abrupt transitions
2 — Hard to follow; sentences seem disconnected or in illogical order
1 — No discernible structure; reads like random unconnected sentences

Think step by step, then output ONLY a single integer (1, 2, 3, 4, or 5). No other text.
Score:""",

    "relevance": """Evaluate the RELEVANCE of the generated Korean summary against the source article.

INPUTS:
[A] Source Article (English):
{source}

[C] Generated Summary (Korean):
{generated_summary}

CRITERION — Relevance (관련성)
Compare [C] vs [A] ONLY.
Question: Does the generated summary cover the key points of the source article?

Scoring rubric:
5 — All key points from the source are present in the summary
4 — Most key points covered; at most one minor point omitted
3 — One important point missing OR the summary focuses on a secondary point
2 — Two or more important points missing
1 — Fails to convey the main topic of the source article

Think step by step, then output ONLY a single integer (1, 2, 3, 4, or 5). No other text.
Score:""",
}

_SCORE_TOKENS = ["1", "2", "3", "4", "5"]


def _logprob_score(client, criterion: str, source: str, generated_summary: str) -> float:
    """
    단일 축 logprobs 가중평균 점수 반환.
    모델이 "Score:" 다음에 올 숫자 토큰("1"~"5")의 확률 분포로 연속형 점수 계산.
    """
    prompt = _CRITERION_TEMPLATES[criterion].format(
        source=source,
        generated_summary=generated_summary,
    )

    response = client.chat.completions.create(
        model=EVAL_MODEL,
        messages=[
            {"role": "system", "content": GEVAL_SYSTEM},
            {"role": "user",   "content": prompt},
        ],
        max_tokens=16,
        temperature=0,
        logprobs=True,
        top_logprobs=10,
    )

    # 첫 번째 생성 토큰의 top_logprobs에서 "1"~"5" 확률 추출
    top = response.choices[0].logprobs.content[0].top_logprobs
    prob_map = {entry.token.strip(): math.exp(entry.logprob) for entry in top}

    weighted_sum = 0.0
    total_prob   = 0.0
    for i, token in enumerate(_SCORE_TOKENS, start=1):
        p = prob_map.get(token, 0.0)
        weighted_sum += i * p
        total_prob   += p

    if total_prob < 1e-9:
        # score 토큰이 top_logprobs에 없는 경우 — 텍스트에서 정수 파싱으로 폴백
        raw_text = response.choices[0].message.content.strip()
        for ch in raw_text:
            if ch in "12345":
                return float(ch)
        return 3.0  # 파싱 불가 시 중앙값

    return weighted_sum / total_prob


def geval_single(
    source: str,
    summary: str,
    gt_summary: str = "",   # 현재 미사용 (logprobs 방식에서 GT는 불필요)
    retries: int = 3,
) -> dict:
    """
    단일 요약문 G-Eval 채점 (4축, logprobs 연속형).

    Returns:
        {
            "consistency":     float,  # 1.0~5.0 연속형
            "fluency":         float,
            "coherence":       float,
            "relevance":       float,
            "g_eval_score":    float,  # 단순평균
            "g_eval_weighted": float,  # 가중평균
        }
    """
    try:
        from openai import OpenAI
    except ImportError:
        raise ImportError("pip install openai")

    if not OPENROUTER_API_KEY:
        raise ValueError("OPENROUTER_API_KEY 환경변수를 설정하세요.")

    client = OpenAI(
        api_key=OPENROUTER_API_KEY,
        base_url=OPENROUTER_BASE_URL,
    )

    src = source[:10000]  # 테스트셋 최대 7433자 → 전체 커버
    gen = summary

    scores = {}
    for criterion in ["consistency", "fluency", "coherence", "relevance"]:
        for attempt in range(retries):
            try:
                scores[criterion] = round(_logprob_score(client, criterion, src, gen), 4)
                break
            except Exception as e:
                if attempt < retries - 1:
                    time.sleep(2)
                else:
                    raise RuntimeError(f"G-Eval [{criterion}] {retries}회 재시도 실패: {e}") from e

    con = scores["consistency"]
    fl  = scores["fluency"]
    coh = scores["coherence"]
    rel = scores["relevance"]

    simple   = round((con + fl + coh + rel) / 4, 4)
    weighted = round(con * 0.4 + rel * 0.3 + fl * 0.2 + coh * 0.1, 4)

    return {
        "consistency":     con,
        "fluency":         fl,
        "coherence":       coh,
        "relevance":       rel,
        "g_eval_score":    simple,
        "g_eval_weighted": weighted,
    }


def batch_geval(
    sources: list[str],
    summaries: list[str],
    gt_summaries: list[str] = None,
    delay: float = 0.3,
) -> dict:
    """여러 요약문 G-Eval 배치 채점."""
    if gt_summaries is None:
        gt_summaries = [""] * len(sources)

    results = []
    for i, (src, summ, gt) in enumerate(zip(sources, summaries, gt_summaries), 1):
        print(f"  G-Eval [{i}/{len(sources)}] 채점 중...")
        result = geval_single(src, summ, gt)
        results.append(result)
        time.sleep(delay)

    def mean(key):
        vals = [r[key] for r in results if r[key] > 0]
        return round(sum(vals) / len(vals), 4) if vals else 0.0

    return {
        "consistency_mean":     mean("consistency"),
        "fluency_mean":         mean("fluency"),
        "coherence_mean":       mean("coherence"),
        "relevance_mean":       mean("relevance"),
        "g_eval_score_mean":    mean("g_eval_score"),
        "g_eval_weighted_mean": mean("g_eval_weighted"),
        "scores":               results,
    }
