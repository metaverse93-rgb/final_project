# 파이프라인 코드 리뷰 — 2026-04-17

## 리뷰 범위
- `eval/run_eval_finetuned.py`
- `eval/run_eval_base.py`
- `eval/metrics/term_preservation.py`
- `eval/metrics/geval.py`
- `eval/metrics/bleu_comet.py`
- `pipeline/translator.py`
- `pipeline/summarizer.py`
- `pipeline/translate_summarize.py`
- `backend/save_articles.py`

---

## CRITICAL — 점수에 직접 영향

### Issue 1: `geval.py` Fluency 기준이 guide v2와 정반대
**파일**: `eval/metrics/geval.py:82-94`

**문제**: G-Eval Fluency 채점 기준이 구 규칙(음차 허용)으로 작성됨.
```
② Standard transliterations: fine-tuning→파인튜닝, embedding→임베딩, prompt→프롬프트
③ Proper nouns FIRST mention: EnglishName(한국어 음차), e.g., OpenAI(오픈에이아이)
```

**충돌**: 파인튜닝 모델의 SUMMARIZE_SYSTEM은 guide v2 기준 (영문 유지):
```
고유명사(회사명·제품명·인물명)는 영문 그대로 유지 (Nvidia, OpenAI ...)
```

**영향**: 파인튜닝 모델이 "Fine-tuning", "Nvidia"를 올바르게 출력해도
G-Eval 평가자가 -1점 패널티를 부과 → G-Eval 점수 억제 (현재 3.64 → 목표 4.0 미달 원인 중 하나).

**수정**: Fluency 기준의 ②③ 항목을 guide v2 기준으로 교체.
```
② AI/기술 용어는 영문 그대로: Fine-tuning, Embedding, Prompt (파인튜닝, 임베딩 사용 시 -1점)
③ 고유명사는 영문만 사용: Nvidia, OpenAI (한국어 음차 사용 시 -1점)
```

---

### Issue 2: `translate_summarize.py` (프로덕션)가 guide v2와 충돌
**파일**: `pipeline/translate_summarize.py:53-68`

**문제**: Rule 3·4가 여전히 음차 규칙 사용.
```python
# Rule 3 — 음차 지시
Fine-tuning→파인튜닝 / Embedding→임베딩 / Prompt→프롬프트 / Transformer→트랜스포머

# Rule 4 — 첫 등장 시 음차 병기
EnglishName(한국어 음차) on FIRST mention only
# e.g., Anthropic(앤트로픽) / OpenAI(오픈에이아이) / Nvidia(엔비디아) ...
```

**영향**:
1. `run_eval_base.py`가 이 함수를 import → 베이스라인 평가 출력에 음차 포함 → TPR 낮게 측정
2. 프로덕션 서비스 출력이 guide v2 불일치 상태
3. 파인튜닝 데이터(guide v2 기준)와 프로덕션 추론 결과가 train/inference mismatch

**수정**: Rule 3을 영문 유지 지시로 변경, Rule 4의 한국어 음차 병기 제거.

---

## MEDIUM — TPR/평가 정확도 영향

### Issue 3: `print_summary()` mean()이 TPR=0을 유효 데이터에서 제외
**파일**: `eval/run_eval_base.py:112`, `eval/run_eval_finetuned.py` 동일 패턴

**문제**:
```python
vals = [float(r[key]) for r in rows if r.get(key) not in ("", "0", "0.0", None)]
```
TPR=0 (용어 완전 미보존)은 실제 발생 가능한 유효한 값인데 평균 계산에서 제외됨.

**영향**: 보고 TPR이 실제보다 높게 나옴 (현재 85.9%가 실제보다 과대 추정일 수 있음).

**수정**: TPR 필터 조건을 빈 값("")과 None만 제외하도록 변경.
```python
vals = [float(r[key]) for r in rows if r.get(key) not in ("", None)]
```
단, BLEU·COMET·G-Eval은 0이 결측값을 의미할 수 있으므로 TPR 키만 선택적으로 적용.

---

### Issue 4: `translator.py` `_ENTITY_RULE` 불완전
**파일**: `pipeline/translator.py:9-14`

**문제**: 회사·제품명 28개만 열거. guide v2 규칙 1이 요구하는 항목 누락.
- 인물명: Jensen Huang, Sam Altman, Elon Musk, Sundar Pichai 등
- 컨퍼런스명: NeurIPS, ICML, CES, TechCrunch Disrupt 등
- 지명: San Francisco, United States, California 등

**영향**: Ollama 기반 프로덕션 translator가 인물명·지명을 한국어로 음차할 수 있음.

**수정**: `_ENTITY_RULE`에 인물명·컨퍼런스·지명 카테고리 추가.

---

### Issue 5: 베이스/파인튜닝 TPR 비교가 비대칭
**파일**: `eval/run_eval_finetuned.py`, `eval/run_eval_base.py`

**문제**:
- 파인튜닝 eval: `translate()` 내부에서 `restore_entities()` 후처리 적용 → 음차 자동 복원 → TPR 상승
- 베이스 eval: `restore_entities()` 미적용 → 음차 그대로 측정 → TPR 낮음

**영향**: 파인튜닝 전/후 TPR 개선폭이 모델 순수 성능이 아닌
"모델 성능 + 후처리" vs "모델 성능만"의 비교가 됨 → 개선율 과대 계상.

**권장 처리**: 비교 방식 확정 후 문서화.
- 옵션 A: 베이스 평가에도 `restore_entities()` 적용 (공정한 순수 모델 비교)
- 옵션 B: 현행 유지 + "파인튜닝 모델은 후처리 포함" 명시 (실제 서비스 조건 반영)

---

## MINOR — 코드 품질

### Issue 6: `bleu_comet.py:85` 불필요한 중복 import
**파일**: `eval/metrics/bleu_comet.py:85`

```python
if model is None:
    from comet import download_model, load_from_checkpoint  # 79행에 이미 동일 import 있음
    model = load_from_checkpoint(download_model(model_name))
```

**수정**: 79행 import를 삭제하고 84-86행으로 통합, 또는 반대로 try 블록 상단으로 이동.

---

### Issue 7: `geval.py:214` JSON 파싱 실패 시 재시도 없이 즉시 반환
**파일**: `eval/metrics/geval.py:214-221`

```python
except (json.JSONDecodeError, KeyError):
    return {"consistency": 0, ...}  # retries 루프 탈출, 재시도 없음
```

파싱 실패 원인이 모델 응답 포맷 불안정(랜덤성)일 경우 재시도 시 성공 가능.

**수정**: `continue` 로 재시도 루프 유지, 마지막 시도에서만 0 반환.

---

## 수정 우선순위 요약

| 우선순위 | 파일 | 이슈 | 예상 효과 |
|---------|------|------|----------|
| 1 (즉시) | `eval/metrics/geval.py` | Fluency 기준 guide v2로 교체 | G-Eval 점수 직접 상승 |
| 2 (즉시) | `pipeline/translate_summarize.py` | Rule 3·4 guide v2로 통일 | 프로덕션 일관성, 베이스 TPR 정확화 |
| 3 (권장) | `eval/run_eval_base.py` + `run_eval_finetuned.py` | TPR mean() 필터 수정 | 보고 수치 정확화 |
| 4 (권장) | `pipeline/translator.py` | `_ENTITY_RULE` 인물명·컨퍼런스 추가 | 프로덕션 TPR 향상 |
| 5 (낮음) | `eval/metrics/bleu_comet.py` | 중복 import 제거 | 코드 정리 |
| 6 (낮음) | `eval/metrics/geval.py` | 파싱 실패 재시도 복원 | G-Eval 안정성 향상 |

---

## 확인 필요 (미검토)
- `pipeline/utils.py` — `preprocess_text()` 동작 확인 필요 (`summarizer.py`에서 사용)
- `supabase_schema.sql` — `title` 컬럼 코멘트 업데이트 완료 여부
