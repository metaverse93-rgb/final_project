"""
RSS 수집 파이프라인
해외 AI 뉴스 피드를 수집하여 기사 목록을 반환합니다.

Usage:
    from pipeline.rss_collector import collect_articles
    articles = collect_articles(max_per_feed=5)
"""

import feedparser
import re
from datetime import datetime, timezone
from typing import Optional

# 수집 대상 AI 뉴스 RSS 피드
RSS_FEEDS = {
    "TechCrunch AI":     "https://techcrunch.com/category/artificial-intelligence/feed/",
    "VentureBeat AI":    "https://venturebeat.com/category/ai/feed/",
    "MIT Tech Review":   "https://www.technologyreview.com/feed/",
    "The Verge AI":      "https://www.theverge.com/ai-artificial-intelligence/rss/index.xml",
    "Wired AI":          "https://www.wired.com/feed/tag/ai/latest/rss",
}


def _clean_html(text: str) -> str:
    """HTML 태그 및 공백 정리"""
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _parse_entry(entry, source_name: str) -> Optional[dict]:
    """feedparser entry → 표준 article dict 변환"""
    title = entry.get("title", "").strip()
    link = entry.get("link", "").strip()

    if not title or not link:
        return None

    # 본문 추출 (content > summary 순서)
    content = ""
    if "content" in entry and entry.content:
        content = _clean_html(entry.content[0].get("value", ""))
    if not content:
        content = _clean_html(entry.get("summary", ""))

    # 발행일 파싱
    published = ""
    if "published_parsed" in entry and entry.published_parsed:
        dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
        published = dt.strftime("%Y-%m-%d %H:%M UTC")

    return {
        "source": source_name,
        "title": title,
        "link": link,
        "content": content,
        "published": published,
    }


def collect_articles(
    feeds: dict = None,
    max_per_feed: int = 5,
) -> list[dict]:
    """
    RSS 피드에서 최신 기사를 수집합니다.

    Args:
        feeds: {이름: URL} dict (기본: RSS_FEEDS)
        max_per_feed: 피드당 최대 수집 기사 수

    Returns:
        [{"source", "title", "link", "content", "published"}, ...]
    """
    if feeds is None:
        feeds = RSS_FEEDS

    articles = []
    for name, url in feeds.items():
        try:
            feed = feedparser.parse(url)
            entries = feed.entries[:max_per_feed]
            for entry in entries:
                article = _parse_entry(entry, name)
                if article:
                    articles.append(article)
            print(f"[수집] {name}: {len(entries)}건")
        except Exception as e:
            print(f"[오류] {name}: {e}")

    return articles


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    articles = collect_articles(max_per_feed=3)
    print(f"\n총 {len(articles)}건 수집\n")
    for a in articles[:3]:
        print(f"[{a['source']}] {a['title']}")
        print(f"  URL: {a['link']}")
        print(f"  날짜: {a['published']}")
        print(f"  본문 미리보기: {a['content'][:100]}...")
        print()
