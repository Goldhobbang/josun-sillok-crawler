"""Integrate local Sillok XML files into a single JSON file.

This module is intentionally separate from ``sillok_crawler.py``:
- ``sillok_crawler.py`` fetches and parses web HTML pages.
- ``sillok_xml_integrator.py`` reads local ``sample/*.xml`` files only.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import xml.etree.ElementTree as ET
from pathlib import Path


XML_DIR = "sample"
OUTPUT_FILE = "sillok_xml_integrated.json"
BASE_ARTICLE_URL = "https://sillok.history.go.kr/id/"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


def normalize_space(text: str) -> str:
    """Collapse repeated whitespace while keeping article text readable."""
    return re.sub(r"\s+", " ", text).strip()


def element_text(elem: ET.Element | None) -> str:
    if elem is None:
        return ""
    return normalize_space("".join(elem.itertext()))


def article_date(level5: ET.Element) -> str:
    date_elem = level5.find("./front/biblioData/date/dateOccured[@type='서기']")
    return date_elem.attrib.get("date", "") if date_elem is not None else ""


def article_title(level5: ET.Element) -> str:
    return element_text(level5.find("./front/biblioData/title/mainTitle"))


def article_content(level5: ET.Element) -> str:
    paragraphs = [
        element_text(paragraph)
        for paragraph in level5.findall("./text/content/paragraph")
    ]
    return "\n".join(paragraph for paragraph in paragraphs if paragraph)


def parse_xml_article(level5: ET.Element, source_file: Path) -> dict[str, str]:
    article_id = level5.attrib.get("id", "")
    return {
        "id": article_id,
        "url": f"{BASE_ARTICLE_URL}{article_id}" if article_id else "",
        "title": article_title(level5),
        "date": article_date(level5),
        "content": article_content(level5),
        "source_file": str(source_file),
    }


def load_xml_articles(xml_file: Path) -> list[dict[str, str]]:
    tree = ET.parse(xml_file)
    root = tree.getroot()

    articles: list[dict[str, str]] = []
    for level5 in root.iter("level5"):
        article = parse_xml_article(level5, xml_file)
        if article["title"] or article["content"]:
            articles.append(article)

    return articles


def save_json(data: list[dict[str, str]], output_file: str | Path = OUTPUT_FILE) -> None:
    Path(output_file).write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def integrate_xml_folder(
    xml_dir: str | Path = XML_DIR,
    output_file: str | Path = OUTPUT_FILE,
) -> list[dict[str, str]]:
    xml_path = Path(xml_dir)
    results: list[dict[str, str]] = []

    for xml_file in sorted(xml_path.glob("*.xml")):
        if xml_file.name.lower() == "history.dtd":
            continue

        try:
            articles = load_xml_articles(xml_file)
        except ET.ParseError as exc:
            logging.warning("XML parse failed: %s - %s", xml_file, exc)
            continue

        results.extend(articles)
        logging.info("Loaded %s articles from %s", len(articles), xml_file)

    save_json(results, output_file)
    logging.info("Saved %s XML articles -> %s", len(results), output_file)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Integrate local Sillok XML files into one JSON file."
    )
    parser.add_argument("--xml-dir", default=XML_DIR, help="Directory containing XML files.")
    parser.add_argument("--out", default=OUTPUT_FILE, help="Output JSON file path.")
    args = parser.parse_args()

    integrate_xml_folder(args.xml_dir, args.out)


if __name__ == "__main__":
    main()
