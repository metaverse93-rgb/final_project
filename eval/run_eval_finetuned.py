"""
파인튜닝 후 평가 (qwen3.5-4b-finetuned)
testset_200.csv → 로컬 LoRA 어댑터 추론 → BLEU/COMET/TPR + G-Eval → results_200_finetuned.csv

실행:
    python eval/run_eval_finetuned.py                    # 전체 200건
    python eval/run_eval_finetuned.py --limit 10         # 빠른 테스트 (10건)
    python eval/run_eval_finetuned.py --skip-geval       # G-Eval 제외 (비용 절약)
    python eval/run_eval_finetuned.py --skip-comet       # COMET 제외 (느릴 때)
    python eval/run_eval_finetuned.py --skip-sheets      # Google Sheets 업로드 제외

결과:
    eval/data/results_200_finetuned.csv  (상세 결과, 베이스라인과 비교용)
    Google Sheets → "파인튜닝_200" 시트
"""

import sys
import os
import csv
import argparse
import time
import torch

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from eval.metrics.bleu_comet import calc_bleu_sentence, load_comet_model, calc_comet
from eval.metrics.term_preservation import check_term_preservation, restore_entities
from eval.metrics.geval import geval_single

# ── 경로 설정 ──────────────────────────────────────────────
TESTSET_PATH   = os.path.join(os.path.dirname(__file__), "data", "testset_200.csv")
RESULTS_PATH   = os.path.join(os.path.dirname(__file__), "data", "results_200_finetuned_8ep.csv")
ADAPTER_PATH   = r"C:\Users\이동우\samseon\samsunmodel3.5_8ep"
CREDENTIALS    = os.path.join(os.path.dirname(__file__), "..",
                              "client_secret_43865832816-letrps5uc0nohpmaug4b5bo6lf2sf92j.apps.googleusercontent.com.json")
SPREADSHEET_ID = "1KV7gEN-lgxREAWenE4lKyFWi3rfwGpHtYIwHdQtp6Po"
SHEET_NAME     = "파인튜닝_8ep"

BASE_MODEL_ID  = "unsloth/Qwen3.5-4B"
MODEL_VERSION  = "qwen3.5-4b-finetuned-8ep"

MAX_NEW_TOKENS_TRANS   = 1024
MAX_NEW_TOKENS_SUMMARY = 256

# ── 학습 시 사용한 시스템 프롬프트 (trainset_chat.jsonl과 동일) ──
TRANSLATE_SYSTEM = (
    "You are a professional AI news translator.\n"
    "Translate the given English news article into natural Korean.\n\n"
    "Rules:\n"
    "- Keep abbreviations like RAG, LLM, GPU, API, NPU, RLHF, SFT, LoRA in English.\n"
    "- CRITICAL: The following company/product names MUST appear in English exactly as written. "
    "NEVER transliterate them into Korean characters under any circumstances:\n"
    "  Nvidia, OpenAI, Anthropic, Google, Meta, Microsoft, Amazon, Apple, Samsung, DeepMind, "
    "  xAI, Mistral, Cohere, Hugging Face, GPT-4, GPT-4o, GPT-5, Claude, Gemini, Llama, "
    "  Grok, Qwen, DeepSeek, ChatGPT, Copilot, Alexa, Siri, GitHub, Slack.\n"
    "- Keep ALL AI/tech terms in English as-is: Fine-tuning, Pre-training, Embedding, Prompt, "
    "Transformer, Attention, Encoder, Decoder, Benchmark, Checkpoint, Inference, Hallucination, "
    "Token, Overfitting, Dataset.\n"
    "- For completely NEW coinages not listed above, use: OriginalTerm(한국어, brief explanation) "
    "on first mention.\n"
    "- Output ONLY the Korean translation. No explanation, no preamble."
)

SUMMARIZE_SYSTEM = (
    "당신은 전문 AI 뉴스 요약가입니다.\n"
    "영어 원문의 핵심 주제와 주요 사실을 기반으로, 한국어 번역문을 참고하여 "
    "정확히 3문장으로 요약하세요.\n\n"
    "규칙:\n"
    "- 반드시 3문장. 각 문장은 원문의 서로 다른 핵심 사실을 다뤄야 합니다.\n"
    "- 원문(영어)에서 다루는 핵심 주제·사실에 충실하게 요약하세요 (Relevance 최우선).\n"
    "- 격식체(~습니다/~됩니다)를 사용하세요.\n"
    "- RAG, LLM, GPU, API 등 약어와 고유명사(Nvidia, OpenAI 등)는 영문 그대로 유지하세요.\n"
    "- 요약문만 출력하세요. 설명이나 서두 없이."
)

RESULT_HEADERS = [
    "id", "model_version", "url", "category",
    "en_text", "ko_gt",
    "translation", "summary_formal",
    "bleu", "comet", "tpr", "tpr_missing",
    "geval_consistency", "geval_fluency", "geval_coherence", "geval_relevance",
    "geval_avg", "geval_weighted",
    "n_sentences",
]


# ══════════════════════════════════════════════════════════════
# 모델 로드
# ══════════════════════════════════════════════════════════════

def load_model():
    """베이스 모델 + LoRA 어댑터 로드"""
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import PeftModel

    from transformers import BitsAndBytesConfig

    print(f"베이스 모델 로딩: {BASE_MODEL_ID}")
    # Unsloth tokenizer_config가 TokenizersBackend 클래스 참조 → 공식 Qwen 토크나이저 사용
    tokenizer = AutoTokenizer.from_pretrained("Qwen/Qwen3.5-4B", trust_remote_code=True)

    # RTX 3070 8.6GB — 4-bit 양자화로 VRAM ~4GB에 올려 peft 어댑터 호환 확보
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_compute_dtype=torch.float16,
        bnb_4bit_use_double_quant=True,
        bnb_4bit_quant_type="nf4",
    )

    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL_ID,
        quantization_config=bnb_config,
        device_map="auto",
        trust_remote_code=True,
    )

    print(f"LoRA 어댑터 적용: {ADAPTER_PATH}")
    model = PeftModel.from_pretrained(model, ADAPTER_PATH)
    model.eval()

    device = next(model.parameters()).device
    print(f"모델 로드 완료 (device: {device})\n")
    return model, tokenizer


# ══════════════════════════════════════════════════════════════
# 추론
# ══════════════════════════════════════════════════════════════

def generate(model, tokenizer, messages: list[dict], max_new_tokens: int) -> str:
    """chat template 적용 후 텍스트 생성"""
    prompt = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
        enable_thinking=False,   # thinking 모드 비활성화 (Qwen3.5 전용)
    )
    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)

    with torch.no_grad():
        output_ids = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            temperature=0.1,
            do_sample=True,
            pad_token_id=tokenizer.eos_token_id,
        )

    new_ids = output_ids[0][inputs["input_ids"].shape[1]:]
    raw = tokenizer.decode(new_ids, skip_special_tokens=True)
    return _clean_output(raw)


def _clean_output(text: str) -> str:
    """think 태그, 마크다운 펜스, 제어문자 제거"""
    import re
    if "</think>" in text:
        text = text.split("</think>")[-1]
    text = re.sub(r"```[a-z]*\s*", "", text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    return text.strip()


def translate(model, tokenizer, en_text: str) -> str:
    messages = [
        {"role": "system", "content": TRANSLATE_SYSTEM},
        {"role": "user",   "content": en_text},
    ]
    result = generate(model, tokenizer, messages, MAX_NEW_TOKENS_TRANS)
    return restore_entities(result)  # 후처리: 음역된 고유명사 영문 복원


def summarize(model, tokenizer, en_text: str, ko_text: str) -> str:
    # 원문(EN) + 번역문(KO) 동시 제공 → Relevance 향상
    # (G-Eval 논문: source alignment가 Relevance 핵심 요인)
    user_content = f"[영어 원문]\n{en_text}\n\n[한국어 번역문]\n{ko_text}"
    messages = [
        {"role": "system", "content": SUMMARIZE_SYSTEM},
        {"role": "user",   "content": user_content},
    ]
    return generate(model, tokenizer, messages, MAX_NEW_TOKENS_SUMMARY)


# ══════════════════════════════════════════════════════════════
# 유틸
# ══════════════════════════════════════════════════════════════

def load_testset(path: str) -> list[dict]:
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def upload_to_sheets(results_path: str):
    try:
        import gspread
        from google_auth_oauthlib.flow import InstalledAppFlow

        SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
        token_path = os.path.join(os.path.dirname(__file__), "..", "token.json")
        creds = None

        if os.path.exists(token_path):
            from google.oauth2.credentials import Credentials
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)

        if not creds or not creds.valid:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS, SCOPES)
            creds = flow.run_local_server(port=0)
            with open(token_path, "w") as f:
                f.write(creds.to_json())

        gc = gspread.authorize(creds)
        sh = gc.open_by_key(SPREADSHEET_ID)

        try:
            ws = sh.worksheet(SHEET_NAME)
            ws.clear()
        except gspread.WorksheetNotFound:
            ws = sh.add_worksheet(title=SHEET_NAME, rows=210, cols=22)

        with open(results_path, encoding="utf-8-sig") as f:
            rows = list(csv.reader(f))

        ws.update(rows, value_input_option="RAW")
        print(f"Google Sheets 업로드 완료: {len(rows)-1}건 → '{SHEET_NAME}' 시트")

    except Exception as e:
        print(f"⚠ Google Sheets 업로드 실패: {e}")


def print_summary(results_path: str):
    if not os.path.exists(results_path):
        return

    with open(results_path, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return

    def mean(key):
        # TPR=0은 유효한 값(용어 완전 미보존)이므로 빈값/None만 제외
        # G-Eval 0은 API 실패를 의미하므로 제외 유지
        if key == "tpr":
            vals = [float(r[key]) for r in rows if r.get(key) not in ("", None)]
        else:
            vals = [float(r[key]) for r in rows if r.get(key) not in ("", "0", "0.0", None)]
        return round(sum(vals) / len(vals), 4) if vals else 0.0

    n = len(rows)
    bleu      = mean("bleu")
    comet     = mean("comet")
    tpr       = mean("tpr")
    geval_avg = mean("geval_avg")
    geval_w   = mean("geval_weighted")
    g_con     = mean("geval_consistency")
    g_fl      = mean("geval_fluency")
    g_coh     = mean("geval_coherence")
    g_rel     = mean("geval_relevance")

    print()
    print("=" * 60)
    print(f"[파인튜닝 후 평가 결과] {MODEL_VERSION}  (n={n})")
    print("=" * 60)
    print(f"  번역 지표")
    print(f"    BLEU  : {bleu:.2f}   (목표 ≥ 17.0)")
    print(f"    COMET : {comet:.4f}  (베이스라인과 비교)")
    print(f"    TPR   : {tpr*100:.1f}%  (목표 ≥ 95%)")
    print()
    print(f"  요약 G-Eval (summary_formal)")
    print(f"    일치성(Consistency) : {g_con:.2f}")
    print(f"    유창성(Fluency)     : {g_fl:.2f}")
    print(f"    일관성(Coherence)   : {g_coh:.2f}")
    print(f"    관련성(Relevance)   : {g_rel:.2f}")
    print(f"    G-Eval 평균         : {geval_avg:.2f}   (목표 ≥ 4.0)")
    print(f"    G-Eval 가중평균     : {geval_w:.2f}")
    print("=" * 60)
    print(f"  결과 파일: {results_path}")
    print()


# ══════════════════════════════════════════════════════════════
# 메인 평가 루프
# ══════════════════════════════════════════════════════════════

def run_eval(limit: int = None, skip_geval: bool = False,
             skip_comet: bool = False, skip_sheets: bool = False):
    print("=" * 60)
    print(f"삼선뉴스 파인튜닝 후 평가 ({MODEL_VERSION})")
    print("=" * 60)

    rows = load_testset(TESTSET_PATH)
    if limit:
        rows = rows[:limit]
    print(f"평가 대상: {len(rows)}건\n")

    # 모델 로드
    model, tokenizer = load_model()

    # COMET 사전 로드
    comet_model = None
    if not skip_comet:
        print("COMET 모델 로딩 중...")
        comet_model = load_comet_model()
        print("COMET 모델 로드 완료\n")

    # 이미 처리된 ID (중단 후 재시작 대비)
    done_ids = set()
    if os.path.exists(RESULTS_PATH):
        with open(RESULTS_PATH, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                done_ids.add(r["id"])
        print(f"이미 처리된 항목: {len(done_ids)}건 스킵\n")

    with open(RESULTS_PATH, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=RESULT_HEADERS)
        if not done_ids:
            writer.writeheader()

        for i, row in enumerate(rows, 1):
            row_id = str(row["id"])
            if row_id in done_ids:
                continue

            en_text    = row.get("원문 (orig_body)", "").strip()
            ko_gt      = row.get("신규 번역 (new_body)", "").strip()
            gt_summary = row.get("신규 3줄 요약 (new_summary)", "").strip()
            url        = row.get("url", "")
            category   = row.get("category", "")

            # 문장 수 추정 (요약 문장 수 상한)
            import re
            parts = re.split(r'(?<=[a-zA-Z]{2})[.!?]\s+', en_text.strip())
            n = min(max(1, len(parts)), 3)

            print(f"[{i}/{len(rows)}] {en_text[:60]}...")

            # ── 1. 번역 ──
            try:
                translation = translate(model, tokenizer, en_text)
            except Exception as e:
                print(f"  ⚠ 번역 오류: {e}")
                translation = ""

            # ── 2. 요약 (원문 EN + 번역문 KO 동시 입력 → Relevance 향상) ──
            summary_formal = ""
            if translation:
                try:
                    summary_formal = summarize(model, tokenizer, en_text, translation)
                except Exception as e:
                    print(f"  ⚠ 요약 오류: {e}")

            # ── 3. BLEU ──
            bleu = calc_bleu_sentence(translation, ko_gt) if translation and ko_gt else 0.0

            # ── 4. COMET ──
            comet_score = 0.0
            if comet_model and translation and ko_gt:
                c = calc_comet([en_text], [translation], [ko_gt], model=comet_model)
                comet_score = c["comet_mean"]

            # ── 5. TPR ──
            tpr_result  = check_term_preservation(translation, source=en_text)
            tpr         = tpr_result["tpr"]
            tpr_missing = "|".join(tpr_result["missing"])

            # ── 6. G-Eval ──
            geval_con = geval_fl = geval_coh = geval_r = geval_avg = geval_weighted = 0.0
            if not skip_geval and summary_formal:
                g = geval_single(en_text, summary_formal, gt_summary=gt_summary)
                geval_con      = g["consistency"]
                geval_fl       = g["fluency"]
                geval_coh      = g["coherence"]
                geval_r        = g["relevance"]
                geval_avg      = g["g_eval_score"]
                geval_weighted = g["g_eval_weighted"]
                time.sleep(0.5)

            writer.writerow({
                "id":                row_id,
                "model_version":     MODEL_VERSION,
                "url":               url,
                "category":          category,
                "en_text":           en_text,
                "ko_gt":             ko_gt,
                "translation":       translation,
                "summary_formal":    summary_formal,
                "bleu":              bleu,
                "comet":             comet_score,
                "tpr":               tpr,
                "tpr_missing":       tpr_missing,
                "geval_consistency": geval_con,
                "geval_fluency":     geval_fl,
                "geval_coherence":   geval_coh,
                "geval_relevance":   geval_r,
                "geval_avg":         geval_avg,
                "geval_weighted":    geval_weighted,
                "n_sentences":       n,
            })
            f.flush()

            print(f"  BLEU={bleu:.1f}  COMET={comet_score:.4f}  TPR={tpr*100:.1f}%  G-Eval={geval_avg:.1f}  G-Eval(W)={geval_weighted:.1f}")

    print(f"\n결과 저장 완료: {RESULTS_PATH}")
    print_summary(RESULTS_PATH)

    if not skip_sheets:
        print("Google Sheets 업로드 중...")
        upload_to_sheets(RESULTS_PATH)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="파인튜닝 후 평가 (testset_200.csv)")
    parser.add_argument("--limit",       type=int,            default=None,  help="평가 건수 제한 (테스트용)")
    parser.add_argument("--skip-geval",  action="store_true",                help="G-Eval 건너뛰기 (비용 절약)")
    parser.add_argument("--skip-comet",  action="store_true",                help="COMET 건너뛰기 (속도 우선)")
    parser.add_argument("--skip-sheets", action="store_true",                help="Google Sheets 업로드 제외")
    parser.add_argument("--output",      type=str,            default=None,  help="결과 파일 경로 지정 (검증용 별도 파일)")
    args = parser.parse_args()

    # --output 지정 시 RESULTS_PATH 임시 변경 (기존 결과 파일 보존)
    if args.output:
        RESULTS_PATH = os.path.join(os.path.dirname(__file__), "data", args.output)

    run_eval(
        limit=args.limit,
        skip_geval=args.skip_geval,
        skip_comet=args.skip_comet,
        skip_sheets=args.skip_sheets,
    )
