# 삼선 프로젝트 진척도 트래커
> 마지막 업데이트: 2026-04-17 (5주차)  
> **업데이트 방법**: 작업 완료 시 `[ ]` → `[x]`, 측정값 나오면 KPI 현황판에 기입

---

## 📊 전체 진척도 요약

| 파이프라인 | 담당 | 상태 | 비고 |
|-----------|------|------|------|
| Collector (수집) | 이상준 | 🟢 완료 | RSS 7개 언론사 |
| Fact-Checker (팩트체크) | 이상준 | 🟡 진행 중 | signal_detector ✅, Gemini 2-Pass 미완 |
| Summarizer (요약) | 이동우 | 🟢 완료 | Qwen3.5-4B 파인튜닝 완료, G-Eval 측정 필요 |
| Translator (번역) | 이동우 | 🟢 완료 | **BLEU 23.96 목표 달성** ✅ |
| RAG-Recommender (추천) | 강주찬 | 🟡 진행 중 | mxbai-embed-large, pgvector |
| Frontend (UI) | 정수민, 김민규 | 🟡 진행 중 | 7개 페이지 구현, 상세 연동 미완 |
| Backend/API | 강주찬 | 🟢 완료 | Railway 배포 완료 |
| QA/통합테스트 | 전체 | 🔴 진행 중 | 5주차 현재 목표 |

---

## 📈 KPI 현황판

| KPI | 목표 | 현재값 | 상태 |
|-----|------|--------|------|
| BLEU (번역, 파인튜닝) | ≥ 17.0 | **23.96** | 🟢 목표 초과 달성 |
| COMET (번역) | ≥ 0.78 | 측정 중 | 🟡 확인 필요 |
| TPR (번역) | ≥ 0.85 | 측정 중 | 🟡 확인 필요 |
| G-EVAL 평균 (요약) | ≥ 4.0 | 측정 중 | 🟡 확인 필요 |
| 신뢰도 정확도 (팩트) | ≥ 80% | 미측정 | 🔴 6주차 예정 |
| Precision@5 (추천) | ≥ 0.6 | 미측정 | 🔴 측정 필요 |

> `eval/data/results_200_finetuned_v2.csv` — 파인튜닝 후 200건 평가 결과 존재  
> `eval/data/results_200_base.csv` — 베이스라인 200건 평가 결과 존재

---

## 1. Collector — 이상준
**코드 위치**: `collect/`

### 완료 ✅
- [x] RSS 피드 파서 (`collect/crawler/rss_crawler.py`)
- [x] BeautifulSoup 정적 크롤링
- [x] URL 해시 중복 제거 (`collect/db/database.py`)
- [x] 언론사별 credibility_score 자동 분류 (`collect/models/credibility.py`)
- [x] Supabase 저장 연동 (`collect/db/`)
- [x] 채널 등급 분류기 (`collect/classifier.py`)

### 미완료
- [ ] cron 1시간 스케줄러 안정화
- [ ] 수집 실패 3회 연속 알림

---

## 2. Fact-Checker — 이상준
**코드 위치**: `fact_checker/`

### 완료 ✅
- [x] 채널 등급 분류 (`fact_checker/channel_config.py`)
- [x] 루머 신호 패턴 매칭 (`fact_checker/signal_detector.py`)
- [x] Google Fact Check API 연동 (`fact_checker/google_fc_api.py`)
- [x] 팩트체크 파이프라인 (`fact_checker/pipeline.py`)

### 미완료
- [ ] Gemini 2-Pass Advisor (Pass A 문체분석, Pass B 상식추론)
- [ ] Google Search Grounding 연동
- [ ] RUMOR/UNVERIFIED 알림 트리거
- [ ] 신뢰도 분류 수동 검증 100건 (6주차)

---

## 3. Summarizer (요약) — 이동우
**코드 위치**: `eval/`, `nb/Qwen3_5_4B_Finetune_ColabPro.ipynb`

### 완료 ✅
- [x] 훈련 데이터셋: `eval/data/trainset_summarize_1116.csv` (1,116쌍)
- [x] 파인튜닝 완료 — Qwen3.5-4B, Unsloth LoRA SFT, A100
- [x] 격식체(`summary_formal`) / 일상체(`summary_casual`) 듀얼 출력
- [x] G-EVAL 평가 코드 (`eval/metrics/geval.py`)
- [x] LLM API 비교 연동 (OpenRouter)

### 측정 필요
- [ ] G-EVAL 4축 최종 수치 확인 (목표: 평균 ≥ 4.0)
  - consistency / fluency / coherence / relevance
- [ ] 파인튜닝 모델 vs 베이스라인 G-EVAL 개선율 비교표

---

## 4. Translator (번역) — 이동우
**코드 위치**: `eval/`, `nb/`

### 완료 ✅ — **BLEU 23.96 목표 초과 달성**
- [x] 훈련 데이터셋: `eval/data/trainset_translate_1000.csv` (1,116쌍)
- [x] 파인튜닝 완료 — Qwen3.5-4B, Unsloth LoRA SFT, A100
- [x] BLEU 평가 (`eval/metrics/bleu_comet.py`)
- [x] COMET 평가 (`eval/metrics/bleu_comet.py`)
- [x] TPR 평가 (`eval/metrics/term_preservation.py`)
- [x] 베이스라인 평가: `eval/data/results_200_base.csv`
- [x] 파인튜닝 후 평가: `eval/data/results_200_finetuned_v2.csv`
- [x] **BLEU 23.96** (목표 17.0 초과 달성)

### 확인 필요
- [ ] COMET 최종 수치 확인 (목표 ≥ 0.78)
- [ ] TPR 최종 수치 확인 (목표 ≥ 0.85)
- [ ] 파인튜닝 전후 개선율 비교표 정리

---

## 5. RAG-Recommender — 강주찬
**코드 위치**: `backend/rag.py`

### 완료 ✅
- [x] Supabase pgvector 세팅
- [x] mxbai-embed-large (1024d) 임베딩 파이프라인
- [x] match_articles RPC (Hybrid Search) 구현
- [x] `backend/save_articles.py` 임베딩 배치 upsert

### 미완료
- [ ] 개인화 피드 유사도 정렬 고도화
- [ ] Context Link (관련 기사 Top-3) 구현
- [ ] Precision@5 측정

---

## 6. Frontend — 정수민, 김민규
**코드 위치**: `frontend/src/`

### 완료 ✅
- [x] React 18 + Vite 5, TDS 기반 세팅
- [x] OnboardingPage (`pages/OnboardingPage.tsx`)
- [x] HomePage (`pages/HomePage.tsx`)
- [x] CategoryPage (`pages/CategoryPage.tsx`)
- [x] HotPage (`pages/HotPage.tsx`)
- [x] MyFeedPage (`pages/MyFeedPage.tsx`)
- [x] SearchPage (`pages/SearchPage.tsx`)
- [x] DetailPage (`pages/DetailPage.tsx`) — 기본 구조
- [x] ArticleCard, TabBar, Skeleton 컴포넌트

### 미완료
- [ ] DetailPage 요약/번역 비교 UI 연동 (파인튜닝 vs LLM API)
- [ ] 격식체/일상체 토글 동작
- [ ] 리포트 전달 버튼 (마크다운 복사)
- [ ] 어드민 페이지 (BLEU/COMET/G-EVAL 모니터링)

---

## 7. Backend/API — 강주찬
**코드 위치**: `backend/`  
**배포**: Railway (`https://natural-illumination-production-c391.up.railway.app/docs`)

### 완료 ✅
- [x] FastAPI 서버 (`backend/main.py`)
- [x] RAG 추천 API (`backend/rag.py`)
- [x] 기사 저장 (`backend/save_articles.py`)
- [x] Railway 배포 완료 (Procfile 존재)

### 미완료
- [ ] GET /article/{id} — 요약/번역 비교 출력 연동
- [ ] GET /report/generate — 리포트 마크다운
- [ ] GET /admin/stats — 모델 성능 모니터링
- [ ] API 응답 시간 최적화

---

## 🗓️ 남은 스프린트

| 주차 | 기간 | 핵심 목표 |
|------|------|----------|
| **5주차 (현재)** | 04.13~04.17 | E2E 통합 테스트, 요약/번역 API 연동, DetailPage 완성 |
| 6주차 | 04.20~04.24 | TPR 95% 후처리, G-Eval Relevance 개선, 신뢰도 100건 검증 |
| 7주차 | 04.27~05.01 | 전체 QA, 사용자 테스트 5명, UX 개선 |
| 8주차 | 05.04~05.08 | 최종 수치 확정, 발표 자료, 시연 영상 |
| 발표 | 05.19~05.20 | 제출(05/19 23:59), 발표(05/20 15:00) |
