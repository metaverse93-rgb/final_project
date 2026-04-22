"""
Term Preservation Rate (TPR)
AI 신조어·고유명사가 번역 출력에 영문 그대로 유지되는지 룰 기반 체크.

목표: TPR ≥ 90%
"""

import re as _re

# 보존해야 할 AI 신조어·고유명사 목록
# 프롬프트 규칙과 동일한 기준으로 관리
AI_TERMS = [
    # 모델·회사명
    "Anthropic", "OpenAI", "Google", "Meta", "Microsoft",
    "Nvidia", "Apple", "Amazon", "Samsung", "DeepMind",
    "xAI", "Mistral", "Cohere", "Stability AI",
    # 모델명
    "GPT-4", "GPT-4o", "GPT-5", "Claude", "Gemini", "Llama",
    "Grok", "Qwen", "DeepSeek", "Falcon", "Mixtral",
    # 기술 용어 (약어)
    "RAG", "LLM", "GPU", "NPU", "API", "RLHF", "SFT",
    "LoRA", "QLoRA", "PEFT", "vLLM",
    # 제품·서비스명
    "ChatGPT", "Copilot", "Alexa", "Siri", "Bard",
    "Slack", "GitHub", "Hugging Face",
    # 하드웨어
    "Blackwell", "Hopper", "H100", "A100", "B200",
]

_URL_PAT = _re.compile(r'https?://\S+')


def check_term_preservation(translation: str, source: str = "", terms: list[str] = None) -> dict:
    """
    번역 출력에서 AI 용어 영문 보존 여부 체크.

    Args:
        translation : 모델 번역 출력 텍스트
        source      : 원본 영어 텍스트 (용어 등장 여부 판단 기준)
                      없으면 translation에서 찾는 방식으로 fallback (비권장)
        terms       : 체크할 용어 리스트 (기본: AI_TERMS)

    Returns:
        {
            "tpr": float,           # Term Preservation Rate (0.0~1.0)
            "preserved": list,      # 보존된 용어
            "missing": list,        # 누락된 용어 (번역됨)
            "checked": list,        # 원문에 등장한 용어 (체크 대상)
        }
    """
    if terms is None:
        terms = AI_TERMS

    base = source if source else translation

    # URL 제거: github.com, ai.meta.com 등 URL 속 소문자 용어가
    # 회사명·제품명으로 잘못 체크되는 것을 방지
    base_no_url = _URL_PAT.sub(' ', base)

    # checked: 대소문자 구분(IGNORECASE 제거) — 영어 원문에서 회사명은 항상 대문자 시작.
    # IGNORECASE를 유지하면 "meta-learning"→Meta, "storage"→RAG 같은 false positive 발생.
    checked = [t for t in terms
               if _re.search(r'\b' + _re.escape(t) + r'\b', base_no_url)]

    # preserved: ASCII + IGNORECASE 조합
    # - ASCII: 한국어 조사(가/이/을/의)가 유니코드 \w로 인식되어 "ChatGPT가"에서
    #          \b 경계가 생기지 않는 문제 해결
    # - IGNORECASE: URL 속 소문자("github.com"→GitHub) 및 번역 대소문자 변형 허용
    preserved = [t for t in checked
                 if _re.search(r'\b' + _re.escape(t) + r'\b', translation, _re.ASCII | _re.IGNORECASE)]
    missing = [t for t in checked if t not in preserved]

    tpr = len(preserved) / len(checked) if checked else 1.0

    return {
        "tpr":       round(tpr, 4),
        "preserved": preserved,
        "missing":   missing,
        "checked":   checked,
    }


# ── 후처리: 음역된 고유명사 영문 복원 ──────────────────────────
# 파인튜닝 모델이 간헐적으로 음역하는 패턴 대응
# (Ugawa et al., 2018 EMNLP — Named Entity Preservation in NMT)

_RESTORE_MAP = [
    # 회사명
    (_re.compile(r"엔비디아"), "Nvidia"),
    (_re.compile(r"오픈에이아이|오픈AI"), "OpenAI"),
    (_re.compile(r"앤트로픽|앤쓰로픽"), "Anthropic"),
    (_re.compile(r"마이크로소프트"), "Microsoft"),
    (_re.compile(r"아마존(?!\s*닷컴)"), "Amazon"),
    (_re.compile(r"딥마인드"), "DeepMind"),
    (_re.compile(r"허깅페이스|허깅 페이스"), "Hugging Face"),
    (_re.compile(r"미스트랄"), "Mistral"),
    (_re.compile(r"코히어"), "Cohere"),
    (_re.compile(r"스태빌리티\s*AI"), "Stability AI"),
    (_re.compile(r"구글"), "Google"),
    (_re.compile(r"슬랙"), "Slack"),
    (_re.compile(r"깃허브|깃 허브"), "GitHub"),
    (_re.compile(r"메타(?=[^데이터이버])"), "Meta"),  # '메타데이터', '메타버스' 오탐 방지
    # 모델명
    (_re.compile(r"지피티[-\s]?4o"), "GPT-4o"),   # 4o 먼저 (4보다 구체적)
    (_re.compile(r"지피티[-\s]?4"), "GPT-4"),
    (_re.compile(r"제미나이"), "Gemini"),
    (_re.compile(r"라마(?=\s*\d|\s*[23])"), "Llama"),
    (_re.compile(r"그록"), "Grok"),
    (_re.compile(r"딥씩|딥시크"), "DeepSeek"),
    (_re.compile(r"챗지피티|챗GPT"), "ChatGPT"),
]


def restore_entities(text: str) -> str:
    """
    파인튜닝 모델이 음역한 고유명사를 영문으로 복원하는 후처리.

    사용 시점: translate() 직후 결과에 적용.
    """
    for pattern, replacement in _RESTORE_MAP:
        text = pattern.sub(replacement, text)
    return text


def batch_tpr(translations: list[str], terms: list[str] = None) -> dict:
    """
    여러 번역 출력의 평균 TPR 계산.

    Returns:
        {"tpr_mean": float, "scores": list[float]}
    """
    scores = [check_term_preservation(t, terms=terms)["tpr"] for t in translations]
    tpr_mean = sum(scores) / len(scores) if scores else 0.0

    return {
        "tpr_mean": round(tpr_mean, 4),
        "scores":   [round(s, 4) for s in scores],
    }
