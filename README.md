# Joseon Sillok Crawler

Joseon Sillok crawling utilities for collecting translated article text from the Sillok website and integrating local Sillok XML files.

## Files

- `sillok_crawler.py`: Web crawler. Starts from a Sillok article URL, follows the next-article link, and saves `url`, `title`, and `content` to JSON.
- `sillok_xml_integrator.py`: XML-only integrator. Reads local XML files and extracts `level5` articles into JSON.
- `convert_to_jsonl.py`: Converts paired original/translation text files into JSONL.

## Setup

Install dependencies:

```bash
pip install -r requirements.txt
```

## Web crawler

The web crawler currently starts from the 680th article in the existing crawl sequence:

```text
https://sillok.history.go.kr/id/kaa_10304029_001
```

Run:

```bash
python sillok_crawler.py
```

Default output:

```text
sillok_translated.json
```

For a short test run, edit `MAX_PAGES` in `sillok_crawler.py`:

```python
MAX_PAGES = 5
```

Set it back to `None` for a full run.

## XML integrator

Place XML files in a local folder such as `sample/`, then run:

```bash
python sillok_xml_integrator.py --xml-dir sample --out sillok_xml_integrated.json
```

The XML output contains:

- `id`
- `url`
- `title`
- `date`
- `content`
- `source_file`

## JSONL converter

Run:

```bash
python convert_to_jsonl.py --orig sample_original.txt --trans sample_translation.txt --out result.jsonl
```

Each output line is a JSON object:

```json
{"original": "...", "translation": "..."}
```

## Notes

- `sample/` is intentionally ignored and should not be committed.
- Generated crawl outputs such as `*.json` and `*.jsonl` are ignored by default.
- JSON files are written as UTF-8 with `ensure_ascii=False`.
