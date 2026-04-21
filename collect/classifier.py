"""
collect/classifier.py — 기사 카테고리 자동 분류

우선순위:
    1. 키워드 매칭 (무료, 즉시) — 제목 가중치 3배
    2. 점수 동점·미결정 시 Ollama 폴백 (선택, 느림)
    3. 최종 미결정 시 소스 기본 카테고리 유지

표준 카테고리 (앱 피드 필터 기준):
    LLM·언어모델 / AI 반도체·하드웨어 / AI 모델·연구 / AI 비즈니스·투자
    AI 윤리·정책 / AI 서비스·제품 / AI 오픈소스 / AI 에이전트·자동화
    AI 로보틱스 / AI 연구·논문 / 테크 일반

사용:
    from collect.classifier import classify
    category = classify(title, content, fallback_category="AI 비즈니스")
"""

import re
import os
from typing import Optional

# ── 카테고리별 키워드 정의 ─────────────────────────────────
# (키워드, 가중치) — 높을수록 확신도 높음
CATEGORY_KEYWORDS: dict[str, list[tuple[str, int]]] = {
    "LLM·언어모델": [
        ("LLM", 3), ("large language model", 3), ("language model", 2),
        ("GPT", 3), ("ChatGPT", 3), ("Claude", 2), ("Gemini", 2),
        ("Llama", 3), ("Mistral", 2), ("Grok", 2), ("DeepSeek", 3),
        ("Phi", 1), ("Gemma", 2), ("Qwen", 2), ("command r", 2),
        ("tokenizer", 2), ("fine-tun", 2), ("파인튜닝", 2),
        ("RLHF", 3), ("instruction tuning", 2), ("alignment", 2),
        ("context window", 2), ("prompt", 1), ("hallucination", 2),
        ("언어 모델", 2), ("대형 언어", 2),
    ],
    "AI 반도체·하드웨어": [
        ("GPU", 3), ("chip", 2), ("semiconductor", 3), ("반도체", 3),
        ("Nvidia", 2), ("CUDA", 3), ("H100", 3), ("H200", 3), ("B200", 3),
        ("Blackwell", 3), ("Hopper", 2), ("TPU", 3), ("NPU", 3),
        ("Intel", 1), ("AMD", 1), ("TSMC", 3), ("wafer", 3),
        ("data center", 1), ("데이터센터", 1), ("inference chip", 3),
        ("AI accelerator", 3), ("HBM", 3), ("VRAM", 2),
        ("GB200", 3), ("DGX", 3), ("compute", 1),
    ],
    "AI 모델·연구": [
        ("model release", 3), ("new model", 2), ("benchmark", 2),
        ("MMLU", 3), ("HumanEval", 3), ("multimodal", 2),
        ("vision model", 2), ("image model", 2), ("diffusion model", 2),
        ("text-to-image", 2), ("Stable Diffusion", 2), ("DALL-E", 2),
        ("Sora", 2), ("video generation", 2), ("audio model", 2),
        ("foundation model", 3), ("model architecture", 2),
        ("transformer", 2), ("attention", 1), ("모델 출시", 2),
        ("성능 비교", 2), ("모델 평가", 2),
    ],
    "AI 비즈니스·투자": [
        ("funding", 3), ("investment", 2), ("valuation", 3),
        ("billion", 1), ("startup", 2), ("스타트업", 2),
        ("series A", 3), ("series B", 3), ("series C", 3),
        ("IPO", 3), ("acquisition", 3), ("인수", 2), ("합병", 2),
        ("revenue", 2), ("profit", 2), ("enterprise", 2),
        ("OpenAI", 1), ("Anthropic", 1), ("Cohere", 2), ("Runway", 2),
        ("투자", 2), ("자금", 2), ("기업 가치", 2), ("deal", 2),
    ],
    "AI 윤리·정책": [
        ("regulation", 3), ("규제", 3), ("policy", 2), ("정책", 2),
        ("EU AI Act", 3), ("AI safety", 3), ("AI 안전", 3),
        ("bias", 2), ("편향", 2), ("fairness", 2),
        ("deepfake", 3), ("딥페이크", 3), ("misinformation", 2),
        ("copyright", 2), ("저작권", 2), ("privacy", 2), ("개인정보", 2),
        ("ethics", 3), ("윤리", 3), ("governance", 2),
        ("ban", 2), ("lawsuit", 2), ("소송", 2), ("Congress", 2),
        ("legislation", 2), ("입법", 2),
    ],
    "AI 서비스·제품": [
        ("launch", 2), ("출시", 2), ("release", 1), ("update", 1),
        ("app", 1), ("product", 1), ("feature", 1), ("기능", 1),
        ("chatbot", 2), ("챗봇", 2), ("assistant", 2), ("어시스턴트", 2),
        ("search", 1), ("검색", 1), ("API", 1),
        ("Microsoft", 1), ("Google", 1), ("Apple", 1), ("Amazon", 1),
        ("Copilot", 2), ("Perplexity", 2), ("사용자", 1),
        ("integration", 2), ("plugin", 2), ("extension", 2),
    ],
    "AI 오픈소스": [
        ("open source", 3), ("오픈소스", 3), ("open-source", 3),
        ("open weight", 3), ("open model", 3),
        ("GitHub", 2), ("repository", 2), ("hugging face", 2),
        ("Hugging Face", 2), ("MIT license", 3), ("Apache license", 3),
        ("community model", 2), ("open release", 2),
        ("Meta AI", 1), ("Llama", 2), ("Mistral", 2),
        ("weights", 2), ("checkpoint", 2),
    ],
    "AI 에이전트·자동화": [
        ("agent", 3), ("에이전트", 3), ("agentic", 3),
        ("multi-agent", 3), ("autonomous", 2), ("자율", 2),
        ("automation", 2), ("자동화", 2),
        ("workflow", 2), ("orchestration", 2),
        ("tool use", 3), ("function calling", 3),
        ("computer use", 3), ("RPA", 3),
        ("AutoGPT", 3), ("CrewAI", 3), ("LangChain", 2),
        ("reasoning", 2), ("planning", 2),
    ],
    "AI 로보틱스": [
        ("robot", 3), ("로봇", 3), ("robotics", 3), ("로보틱스", 3),
        ("autonomous vehicle", 3), ("자율주행", 3), ("self-driving", 3),
        ("drone", 2), ("드론", 2), ("humanoid", 3), ("휴머노이드", 3),
        ("physical AI", 3), ("embodied", 3),
        ("Boston Dynamics", 3), ("Tesla Optimus", 3),
        ("manipulation", 2), ("locomotion", 2), ("sensor", 1),
    ],
    "AI 연구·논문": [
        ("paper", 2), ("논문", 2), ("research", 2), ("연구", 1),
        ("arXiv", 3), ("arxiv", 3), ("preprint", 3),
        ("study", 1), ("experiment", 2), ("실험", 2),
        ("published", 1), ("journal", 2), ("conference", 2),
        ("NeurIPS", 3), ("ICML", 3), ("ICLR", 3), ("ACL", 3),
        ("AAAI", 3), ("CVPR", 3), ("학회", 2),
        ("scientists", 1), ("researchers", 1), ("연구진", 2),
    ],
    "테크 일반": [
        ("smartphone", 2), ("스마트폰", 2), ("social media", 2),
        ("SNS", 2), ("streaming", 2), ("스트리밍", 2),
        ("gaming", 2), ("게임", 1), ("cybersecurity", 2), ("보안", 1),
        ("blockchain", 2), ("crypto", 2), ("metaverse", 2),
        ("cloud", 1), ("클라우드", 1), ("5G", 2), ("IoT", 2),
    ],
}

# 카테고리 우선순위 (동점 시 앞쪽 우선)
CATEGORY_PRIORITY = [
    "LLM·언어모델",
    "AI 반도체·하드웨어",
    "AI 에이전트·자동화",
    "AI 로보틱스",
    "AI 오픈소스",
    "AI 연구·논문",
    "AI 모델·연구",
    "AI 윤리·정책",
    "AI 비즈니스·투자",
    "AI 서비스·제품",
    "테크 일반",
]

# 소스 기본 카테고리 → 표준 카테고리 매핑 (레거시 호환)
LEGACY_CATEGORY_MAP = {
    "AI/스타트업":    "AI 비즈니스·투자",
    "AI 심층":        "AI 모델·연구",
    "AI 심층/기술":   "AI 모델·연구",
    "테크 전반":      "AI 서비스·제품",
    "AI 비즈니스":    "AI 비즈니스·투자",
    "AI 윤리":        "AI 윤리·정책",
    "AI/반도체":      "AI 반도체·하드웨어",
    "AI 커뮤니티":    "AI 서비스·제품",
    "AI 연구":        "AI 연구·논문",
    "LLM 커뮤니티":   "LLM·언어모델",
    "AI 제품":        "AI 서비스·제품",
}

# 최소 신뢰 점수 (이 이상일 때만 키워드 분류 결과 채택)
MIN_CONFIDENCE_SCORE = 4


def _score(text: str, keywords: list[tuple[str, int]]) -> int:
    """텍스트에서 키워드 가중치 합산."""
    t = text.lower()
    total = 0
    for kw, weight in keywords:
        if kw.lower() in t:
            total += weight
    return total


def classify_by_keywords(title: str, content: str) -> tuple[str, int]:
    """
    키워드 기반 분류.
    제목에 가중치 3배 적용 (제목이 카테고리를 더 잘 나타냄).

    Returns:
        (category, score) — score가 MIN_CONFIDENCE_SCORE 미만이면 불확실
    """
    # 제목 3배 가중
    search_text = (title + " ") * 3 + content[:500]

    scores: dict[str, int] = {}
    for cat, keywords in CATEGORY_KEYWORDS.items():
        scores[cat] = _score(search_text, keywords)

    # 우선순위 순으로 최고점 카테고리 선택
    best_cat = max(CATEGORY_PRIORITY, key=lambda c: scores.get(c, 0))
    best_score = scores.get(best_cat, 0)

    return best_cat, best_score


def classify_by_ollama(title: str, content: str) -> Optional[str]:
    """
    Ollama(qwen3.5:4b) 기반 분류 폴백.
    키워드 점수가 낮을 때만 호출. 실패해도 None 반환 (크래시 없음).
    """
    try:
        import ollama

        categories_str = " / ".join(CATEGORY_PRIORITY)
        prompt = (
            f"다음 AI 뉴스 기사의 카테고리를 아래 목록 중 하나만 골라 출력하세요.\n"
            f"카테고리 목록: {categories_str}\n\n"
            f"제목: {title}\n"
            f"본문 요약: {content[:300]}\n\n"
            f"카테고리 하나만 출력 (설명 없이):"
        )

        resp = ollama.chat(
            model=os.getenv("MODEL_NAME", "qwen3.5:4b"),
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0, "num_predict": 30},
            think=False,
        )
        result = resp.message.content.strip()

        # 출력된 텍스트에서 표준 카테고리 매칭
        for cat in CATEGORY_PRIORITY:
            if cat in result:
                return cat

        return None

    except Exception:
        return None


def classify(
    title: str,
    content: str,
    fallback_category: str = "AI 서비스·제품",
    use_ollama: bool = False,
) -> str:
    """
    기사 카테고리 분류 메인 함수.

    Args:
        title:             기사 제목 (영문)
        content:           기사 본문 (영문)
        fallback_category: 분류 실패 시 사용할 기본 카테고리
                           (RSS 피드의 source 카테고리를 넘기면 됨)
        use_ollama:        True이면 키워드 점수 낮을 때 Ollama 폴백 사용
                           (기본 False — 속도 우선)

    Returns:
        표준 카테고리 문자열
    """
    # 레거시 카테고리 → 표준 카테고리 변환
    normalized_fallback = LEGACY_CATEGORY_MAP.get(fallback_category, fallback_category)

    if not title and not content:
        return normalized_fallback

    cat, score = classify_by_keywords(title, content)

    # 점수 충분 → 키워드 분류 결과 채택
    if score >= MIN_CONFIDENCE_SCORE:
        return cat

    # 점수 낮음 → Ollama 폴백 (옵션)
    if use_ollama:
        ollama_cat = classify_by_ollama(title, content)
        if ollama_cat:
            return ollama_cat

    # 최종 폴백 — 소스 기본 카테고리
    return normalized_fallback


def normalize_legacy(category: str) -> str:
    """
    기존 RSS 피드 카테고리 문자열을 표준 카테고리로 변환.
    rss_crawler.py의 feed_info["category"] 값을 정규화할 때 사용.
    """
    return LEGACY_CATEGORY_MAP.get(category, category)
