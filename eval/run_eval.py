"""
평가 실행기
testset_1000.csv → Qwen3 추론 → BLEU/COMET/TPR + G-Eval → results.csv

실행:
    python eval/run_eval.py                    # 전체 1000건
    python eval/run_eval.py --limit 10         # 빠른 테스트 (10건)
    python eval/run_eval.py --skip-geval       # G-Eval 제외 (OpenRouter 비용 절약)

결과:
    eval/data/results.csv   (상세 결과)
"""

import sys
import os
import csv
import argparse
import time

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "RSS"))

from pipeline.translate_summarize import translate_and_summarize, estimate_sentences
from eval.metrics.bleu_comet import calc_bleu_sentence
from eval.metrics.term_preservation import check_term_preservation
from eval.metrics.geval import geval_single

TESTSET_PATH = os.path.join(os.path.dirname(__file__), "data", "testset_1000.csv")
RESULTS_PATH = os.path.join(os.path.dirname(__file__), "data", "results.csv")

RESULT_HEADERS = [
    "id", "url", "category",
    "en_text", "ko_gt",
    "translation", "summary_formal",
    "bleu", "tpr", "tpr_missing",
    "geval_faithfulness", "geval_fluency", "geval_conciseness", "geval_avg",
    "n_sentences",
]


def load_testset(path: str) -> list[dict]:
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def run_eval(limit: int = None, skip_geval: bool = False):
    print("=" * 60)
    print("삼선뉴스 번역·요약 평가 시작")
    print("=" * 60)

    rows = load_testset(TESTSET_PATH)
    if limit:
        rows = rows[:limit]
    print(f"평가 대상: {len(rows)}건\n")

    # 이미 처리된 ID 확인 (중단 후 재시작 대비)
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

        for row in rows:
            if row["id"] in done_ids:
                continue

            en_text = row["en_text"]
            ko_gt   = row["ko_text"]
            print(f"[{row['id']}/{len(rows)}] {en_text[:60]}...")

            # ── 1. 번역 + 요약 (Qwen3) ──
            try:
                n = estimate_sentences(en_text)
                result = translate_and_summarize(en_text, summary_sentences=n)
                translation    = result.get("translation", "")
                summary_formal = result.get("summary_formal", "")
            except Exception as e:
                print(f"  ⚠ Qwen3 오류: {e}")
                translation = summary_formal = ""

            # ── 2. BLEU (문장 단위) ──
            bleu = calc_bleu_sentence(translation, ko_gt) if translation else 0.0

            # ── 3. TPR ──
            tpr_result  = check_term_preservation(translation)
            tpr         = tpr_result["tpr"]
            tpr_missing = "|".join(tpr_result["missing"])

            # ── 4. G-Eval (요약, 옵션) ──
            geval_f = geval_fl = geval_c = geval_avg = 0.0
            if not skip_geval and summary_formal:
                g = geval_single(en_text, summary_formal)
                geval_f   = g["faithfulness"]
                geval_fl  = g["fluency"]
                geval_c   = g["conciseness"]
                geval_avg = g["average"]
                time.sleep(0.5)  # Rate Limit 방지

            writer.writerow({
                "id":                   row["id"],
                "url":                  row["url"],
                "category":             row["category"],
                "en_text":              en_text,
                "ko_gt":                ko_gt,
                "translation":          translation,
                "summary_formal":       summary_formal,
                "bleu":                 bleu,
                "tpr":                  tpr,
                "tpr_missing":          tpr_missing,
                "geval_faithfulness":   geval_f,
                "geval_fluency":        geval_fl,
                "geval_conciseness":    geval_c,
                "geval_avg":            geval_avg,
                "n_sentences":          row["n_sentences"],
            })
            f.flush()  # 중간 저장

            print(f"  BLEU={bleu:.1f}  TPR={tpr:.2f}  G-Eval={geval_avg:.1f}")

    print(f"\n결과 저장 완료: {RESULTS_PATH}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit",      type=int,  default=None,  help="평가 건수 제한 (테스트용)")
    parser.add_argument("--skip-geval", action="store_true",      help="G-Eval 건너뛰기")
    args = parser.parse_args()

    run_eval(limit=args.limit, skip_geval=args.skip_geval)
