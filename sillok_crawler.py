"""
조선왕조실록 국역 기사 linked crawler.

시작 기사 URL에서 출발해 상세 페이지의 "다음 기사" 링크/ID를 따라가며
기사 제목과 국역 본문만 수집한 뒤 JSON으로 저장합니다.

필요 패키지:
    pip install requests beautifulsoup4

실행:
    python sillok_crawler.py
"""

from __future__ import annotations

import json
import logging
import random
import re
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


# Continue web crawling from the 680th article in the existing crawl result.
START_URL = "https://sillok.history.go.kr/id/kaa_10304029_001"
OUTPUT_FILE = "sillok_translated.json"
SAVE_EVERY = 10
MAX_PAGES: Optional[int] = None  # 테스트할 때는 5, 10처럼 지정하세요.
REQUEST_TIMEOUT = 15
MAX_RETRIES = 3

BASE_URL = "https://sillok.history.go.kr"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

session = requests.Session()
session.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0 Safari/537.36"
        ),
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    }
)


def clean_text(text: str) -> str:
    """공백을 정리하되 문단 구분은 최대한 유지합니다."""
    lines = []
    for line in text.splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def normalize_space(text: str) -> str:
    """한 줄짜리 제목/문단에서 불필요한 공백을 정리합니다."""
    return re.sub(r"\s+", " ", text).strip()


def extract_paragraph_text(elem) -> str:
    paragraphs = elem.select("p.paragraph, p")
    if paragraphs:
        return "\n".join(
            paragraph
            for paragraph in (
                normalize_space(p.get_text(" ", strip=True)) for p in paragraphs
            )
            if paragraph
        )
    return clean_text(elem.get_text("\n", strip=True))


def fetch_html(url: str) -> Optional[str]:
    """일시적인 네트워크 오류를 재시도하며 HTML을 가져옵니다."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = session.get(url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            response.encoding = response.apparent_encoding or "utf-8"
            return response.text
        except requests.RequestException as exc:
            logging.warning("요청 실패 (%s/%s): %s - %s", attempt, MAX_RETRIES, url, exc)
            if attempt < MAX_RETRIES:
                time.sleep(random.uniform(1, 3))

    logging.error("재시도 후에도 요청 실패: %s", url)
    return None


def extract_title(soup: BeautifulSoup) -> str:
    """
    기사 제목을 추출합니다.
    예전 구조의 .ins_view_tit를 먼저 보고, 현재 구조의 .detail-view를 fallback으로 봅니다.
    """
    title_box = soup.select_one(".ins_view_tit")
    if title_box:
        return clean_text(title_box.get_text("\n", strip=True))

    title_head = soup.select_one(".detail-view .title-head .title")
    if title_head:
        date = title_head.select_one(".date")
        headline = title_head.find(["h1", "h2", "h3", "h4"])
        parts = [
            normalize_space(date.get_text(" ", strip=True)) if date else "",
            normalize_space(headline.get_text(" ", strip=True)) if headline else "",
        ]
        return "\n".join(part for part in parts if part)

    heading = soup.select_one("h1, h2, h3")
    return clean_text(heading.get_text(" ", strip=True)) if heading else ""


def extract_translation(soup: BeautifulSoup) -> str:
    """
    국역 본문만 추출합니다.
    - 현재 구조: .view-item 안에서 h4.view-title == 국역인 영역의 .view-text
    - 예전/다른 구조: .ins_view_pd 내부에서 국역 영역 추정
    """
    for item in soup.select(".detail-view .view-area .view-item, .detail-mobile-view .view-area .view-item"):
        title = item.select_one(".view-title")
        if title and "국역" in title.get_text(" ", strip=True):
            text_box = item.select_one(".view-text") or item
            return extract_paragraph_text(text_box)

    for selector in [
        ".ins_view_pd .view-text",
        ".ins_view_pd .paragraph",
        ".ins_view_pd",
        ".ins_text.ko",
        ".ins_ko",
        ".trans_txt",
        "div.paragraph.ko",
    ]:
        elem = soup.select_one(selector)
        if elem:
            text = extract_paragraph_text(elem)
            text = re.split(r"\n?원문\n?", text, maxsplit=1)[0]
            text = re.split(r"\n?분류\n?", text, maxsplit=1)[0]
            if text:
                return text

    return ""


def extract_next_url(soup: BeautifulSoup, html: str, current_url: str) -> Optional[str]:
    """
    다음 기사 URL을 찾습니다.
    1) 실제 다음 버튼 href에서 abSearch('기사ID') 또는 /id/기사ID 추출
    2) 스크립트의 nextId 값을 fallback으로 사용
    """
    next_selectors = [
        "a.btn-item.next2[href]",
        "a[title*='뒷문서'][href]",
        "a[title*='다음'][href]",
        "a.next[href]",
        "a[class*='next'][href]",
    ]

    for selector in next_selectors:
        link = soup.select_one(selector)
        if not link:
            continue

        href = link.get("href", "").strip()
        if not href or href == "#":
            continue

        id_match = re.search(r"abSearch\(['\"]([^'\"]+)['\"]\)", href)
        if id_match:
            return f"{BASE_URL}/id/{id_match.group(1)}"

        if "/id/" in href:
            return urljoin(current_url, href)

    next_id_match = re.search(r"nextId\s*=\s*['\"]([^'\"]+)['\"]", html)
    if next_id_match and next_id_match.group(1).strip():
        return f"{BASE_URL}/id/{next_id_match.group(1).strip()}"

    return None


def save_json(data: list[dict[str, str]], output_file: str = OUTPUT_FILE) -> None:
    Path(output_file).write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def crawl_linked_articles(
    start_url: str = START_URL,
    output_file: str = OUTPUT_FILE,
    max_pages: Optional[int] = MAX_PAGES,
) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    visited: set[str] = set()
    current_url: Optional[str] = start_url

    while current_url:
        if current_url in visited:
            logging.warning("이미 방문한 URL이 다시 나와 종료합니다: %s", current_url)
            break
        if max_pages is not None and len(results) >= max_pages:
            logging.info("max_pages=%s에 도달해 종료합니다.", max_pages)
            break

        visited.add(current_url)
        logging.info("[%s] 수집 중: %s", len(results) + 1, current_url)

        html = fetch_html(current_url)
        if html is None:
            break

        try:
            soup = BeautifulSoup(html, "html.parser")
            title = extract_title(soup)
            content = extract_translation(soup)
            next_url = extract_next_url(soup, html, current_url)

            if not title:
                logging.warning("제목을 찾지 못했습니다: %s", current_url)
            if not content:
                logging.warning("국역 본문을 찾지 못했습니다: %s", current_url)

            results.append(
                {
                    "url": current_url,
                    "title": title,
                    "content": content,
                }
            )

            if len(results) % SAVE_EVERY == 0:
                save_json(results, output_file)
                logging.info("중간 저장 완료: %s개 -> %s", len(results), output_file)

            if not next_url:
                logging.info("다음 기사 링크가 없어 정상 종료합니다.")
                break

            current_url = next_url
        except Exception as exc:
            logging.exception("파싱 오류 발생: %s - %s", current_url, exc)
            current_url = extract_next_url(BeautifulSoup(html, "html.parser"), html, current_url)
            if not current_url:
                break

        time.sleep(random.uniform(1, 3))

    save_json(results, output_file)
    logging.info("최종 저장 완료: %s개 -> %s", len(results), output_file)
    return results


if __name__ == "__main__":
    crawl_linked_articles()
