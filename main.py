import sys
sys.stdout.reconfigure(encoding='utf-8')

from pipeline.rss_collector import collect_articles
from pipeline.translate_summarize import translate_and_summarize

def run_pipeline(max_per_feed: int = 2, summary_sentences: int = 3):
    """RSS 수집 → 번역+요약 전체 파이프라인"""

    print("=" * 60)
    print("[ 1단계: RSS 수집 ]")
    print("=" * 60)
    articles = collect_articles(max_per_feed=max_per_feed)
    print(f"\n총 {len(articles)}건 수집 완료\n")

    print("=" * 60)
    print("[ 2단계: 번역 + 요약 ]")
    print("=" * 60)

    results = []
    for i, article in enumerate(articles, 1):
        print(f"\n[{i}/{len(articles)}] {article['title'][:60]}...")
        try:
            processed = translate_and_summarize(
                article["content"] or article["title"],
                summary_sentences=summary_sentences,
            )
            result = {
                **article,
                "translation":    processed.get("translation", ""),
                "summary_formal": processed.get("summary_formal", ""),
                "summary_casual": processed.get("summary_casual", ""),
            }
            results.append(result)

            print(f"  [번역]      {result['translation'][:50]}...")
            print(f"  [격식체 요약] {result['summary_formal'][:50]}...")
            print(f"  [일상체 요약] {result['summary_casual'][:50]}...")
        except Exception as e:
            print(f"  오류: {e}")
            results.append({**article, "translation": "", "summary": ""})

    return results


if __name__ == "__main__":
    results = run_pipeline(max_per_feed=2, summary_sentences=3)
    print(f"\n파이프라인 완료: {len(results)}건 처리")
