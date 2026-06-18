"""
조선왕조실록 병렬 크롤러 및 XML 통합 스크립트 (안전 & 효율 중심)

1. 효율적인 XML 파싱: lxml의 iterparse 또는 최적화된 ET를 사용해 대용량 XML에서도 메모리를 적게 소모하며 ID와 원문을 추출합니다.
2. 안전한 병렬 크롤링: ThreadPoolExecutor를 사용하되, 서버에 무리를 주지 않도록 
   - 최대 스레드 수를 제한 (MAX_WORKERS = 3)
   - 각 요청 간 무작위 지연(Sleep) 부여
   - 재시도(Retry) 로직과 실패 처리 강화
3. 최종 저장: 병렬 처리로 인해 뒤섞이는 순서를 고려하여 JSONL(Line-by-Line) 방식으로 
   데이터를 Thread-safe하게 실시간 Append 합니다.

필요 패키지:
    pip install requests beautifulsoup4 lxml

실행:
    python sillok_parallel_crawler.py
"""

from __future__ import annotations

import json
import logging
import random
import re
import time
import threading
import queue
from pathlib import Path
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET


# ==========================================
# 설정 (Configuration)
# ==========================================
XML_DIR = "sample"
CHECKPOINT_FILE = "parallel_crawled_ids.txt"
OUTPUT_FILE = "sillok_parallel_final.jsonl"
BASE_URL = "https://sillok.history.go.kr"

# 안전을 위한 크롤링 설정
MAX_WORKERS = 3       # 동시 요청 수 (3~5 이하 권장)
REQUEST_TIMEOUT = 15  # 초
MAX_RETRIES = 3       # 실패 시 재시도 횟수

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - [%(threadName)s] %(message)s",
)

# 스레드 안전하게 파일에 기록하기 위한 Lock
file_lock = threading.Lock()

# 전역 세션 (세션 풀링을 통해 연결 부하 감소, 스레드 안전은 requests Session 특성상 일부 보장되나 
# 완벽을 기하기 위해 스레드 로컬 세션을 만들거나 매번 호출할 수 있음. 여기서는 로컬을 사용)
thread_local = threading.local()

def get_session():
    if not hasattr(thread_local, "session"):
        thread_local.session = requests.Session()
        thread_local.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0 Safari/537.36"
                ),
                "Accept-Language": "ko-KR,ko;q=0.9",
            }
        )
    return thread_local.session


# ==========================================
# 1. 효율적인 XML 파싱 (메모리 절약)
# ==========================================
def parse_xml_dump(xml_file_path: Path) -> dict[str, dict]:
    """
    iterparse를 활용한 메모리 효율적 XML 파싱.
    level5(기사 단위)를 만나면 파싱 후 즉시 메모리에서 해제합니다.
    """
    xml_data = {}
    logging.info(f"XML 파싱 시작: {xml_file_path}")
    
    current_date = ""
    
    try:
        context = ET.iterparse(xml_file_path, events=('start', 'end'))
        
        for event, elem in context:
            # 날짜 정보 업데이트 (level4의 서기/재위연도 등)
            if event == 'end' and elem.tag == 'dateOccured' and elem.get('type') == '재위연도':
                if elem.text:
                    current_date = elem.text.strip()
                    
            if event == 'end' and elem.tag == 'level5':
                article_id = elem.get('id')
                if not article_id:
                    elem.clear()
                    continue
                
                title_elem = elem.find('.//mainTitle')
                title = title_elem.text.strip() if title_elem is not None and title_elem.text else ""
                
                source_elem = elem.find('.//source/mainTitle')
                source_text = source_elem.text.strip() if source_elem is not None and source_elem.text else ""
                
                era = source_text.split()[0] if source_text else ""
                volume = source_text.split()[-1] if source_text else ""
                
                paragraphs = elem.findall('.//content/paragraph')
                hanja_text = []
                for p in paragraphs:
                    text = "".join(p.itertext()).strip()
                    text = re.sub(r"\s+", " ", text).strip()
                    if text:
                        hanja_text.append(text)
                
                xml_data[article_id] = {
                    "era": era,
                    "volume": volume,
                    "date_korean": current_date,
                    "title_xml": title,
                    "original_hanja_xml": "\n".join(hanja_text)
                }
                
                # 메모리 해제
                elem.clear()
                
    except Exception as e:
        logging.error(f"XML 파싱 에러 ({xml_file_path}): {e}")
        
    logging.info(f"XML 파싱 완료. 추출된 기사 수: {len(xml_data)}")
    return xml_data


# ==========================================
# 2. 웹 크롤링 유틸 (본문 추출)
# ==========================================
def extract_translation(soup: BeautifulSoup) -> str:
    """국역 본문만 안전하게 추출합니다."""
    for item in soup.select(".detail-view .view-area .view-item"):
        title = item.select_one(".view-title")
        if title and "국역" in title.get_text(" ", strip=True):
            text_box = item.select_one(".view-text") or item
            
            paragraphs = text_box.select("p.paragraph, p")
            if paragraphs:
                return "\n".join(re.sub(r"\s+", " ", p.get_text(" ", strip=True)).strip() for p in paragraphs if p.get_text(strip=True))
            return re.sub(r"\s+", " ", text_box.get_text("\n", strip=True)).strip()
            
    # Fallback (과거 구조)
    for selector in [".ins_view_pd .paragraph", ".ins_text.ko", ".trans_txt"]:
        elem = soup.select_one(selector)
        if elem:
            text = re.sub(r"\s+", " ", elem.get_text(" ", strip=True)).strip()
            text = re.split(r"원문", text, maxsplit=1)[0]
            if text:
                return text
                
    return ""


def download_and_parse(article_id: str, xml_info: dict) -> Optional[dict]:
    """단일 기사를 크롤링하고 XML 데이터와 병합하여 반환합니다."""
    session = get_session()
    
    # XML 아이디(wya_...)를 웹 한글번역 아이디(kya_...)로 변환
    web_id = "k" + article_id[1:] if article_id.startswith("w") else article_id
    url = f"{BASE_URL}/id/{web_id}"
    
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            # 안전을 위한 무작위 지연 (서버 부하 방지)
            time.sleep(random.uniform(0.8, 2.5))
            
            response = session.get(url, timeout=REQUEST_TIMEOUT)
            if response.status_code == 404:
                logging.warning(f"404 Not Found: {web_id}")
                return None
            response.raise_for_status()
            
            response.encoding = response.apparent_encoding or "utf-8"
            soup = BeautifulSoup(response.text, "html.parser")
            
            translation_ko = extract_translation(soup)
            
            # 병합된 데이터 생성
            merged_item = {
                "article_id": web_id,
                "xml_id": article_id,
                "era": xml_info.get("era", ""),
                "volume": xml_info.get("volume", ""),
                "date_korean": xml_info.get("date_korean", ""),
                "title": xml_info.get("title_xml", ""),
                "original_hanja": xml_info.get("original_hanja_xml", ""),
                "translation_ko": translation_ko,
                "source_url": url
            }
            
            return merged_item
            
        except requests.RequestException as exc:
            logging.warning(f"요청 실패 ({attempt}/{MAX_RETRIES}) - {url}: {exc}")
            time.sleep(random.uniform(2, 5))  # 실패 시 좀 더 길게 대기
            
    logging.error(f"최종 실패: {url}")
    return None


# ==========================================
# 3. 병렬 처리 매니저
# ==========================================
def load_checkpoint() -> set:
    if Path(CHECKPOINT_FILE).exists():
        with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    return set()


def append_to_jsonl(data: dict):
    with file_lock:
        with open(OUTPUT_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False) + "\n")
        
        # 체크포인트 기록
        with open(CHECKPOINT_FILE, "a", encoding="utf-8") as f:
            f.write(data["xml_id"] + "\n")


def run_parallel_crawler(xml_data: dict[str, dict]):
    completed_ids = load_checkpoint()
    
    # 크롤링할 작업 필터링 (완료된 것 제외)
    tasks = {xml_id: info for xml_id, info in xml_data.items() if xml_id not in completed_ids}
    total_tasks = len(tasks)
    
    if total_tasks == 0:
        logging.info("모든 기사가 이미 크롤링되었습니다.")
        return

    logging.info(f"병렬 크롤링 시작. 총 대상: {total_tasks}건 (스레드 수: {MAX_WORKERS})")
    
    success_count = 0
    fail_count = 0

    # ThreadPoolExecutor를 사용한 병렬 처리
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # 작업 제출
        future_to_id = {
            executor.submit(download_and_parse, xml_id, info): xml_id 
            for xml_id, info in tasks.items()
        }
        
        # 완료되는 대로 결과 처리
        for future in as_completed(future_to_id):
            xml_id = future_to_id[future]
            try:
                result = future.result()
                if result:
                    append_to_jsonl(result)
                    success_count += 1
                    logging.info(f"[진척도: {success_count+fail_count}/{total_tasks}] 성공: {result['article_id']}")
                else:
                    fail_count += 1
            except Exception as exc:
                fail_count += 1
                logging.exception(f"작업 처리 중 예외 발생 ({xml_id}): {exc}")

    logging.info(f"병렬 크롤링 종료. 성공: {success_count}, 실패(또는 누락): {fail_count}")


# ==========================================
# Main
# ==========================================
def main():
    print("=== 조선왕조실록 병렬 수집 파이프라인 (안전모드) ===")
    
    # 1. XML 폴더에서 모든 XML 파싱 통합
    all_xml_data = {}
    xml_dir_path = Path(XML_DIR)
    
    if not xml_dir_path.exists():
        logging.error(f"{XML_DIR} 디렉터리가 없습니다.")
        return
        
    for xml_file in xml_dir_path.glob("*.xml"):
        if xml_file.name.lower() == "history.dtd":
            continue
        data = parse_xml_dump(xml_file)
        all_xml_data.update(data)
        
    if not all_xml_data:
        logging.error("XML 데이터를 읽지 못했습니다.")
        return
        
    # 2. 병렬 크롤링 및 병합, 저장 실행
    run_parallel_crawler(all_xml_data)
    
    print("=== 작업 완료 ===")


if __name__ == "__main__":
    main()