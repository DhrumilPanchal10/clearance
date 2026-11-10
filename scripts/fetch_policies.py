"""Fetch the real public Medicare coverage documents for the M1 procedures (T1.2).

Downloads each CMS coverage document, extracts its text and stated effective
date, and writes a front-matter'd Markdown file into ``data/policies/raw/`` for
``policies.ingest`` to load. Run once:

    uv run python -m scripts.fetch_policies

Only public CMS documents are fetched. Source URLs and effective dates are
recorded in each file's front matter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path

import httpx

RAW_DIR = Path("data/policies/raw")
UA = "clearance-research-bot/0.1 (synthetic prior-auth demo; coverage-policy fetch)"


@dataclass(frozen=True)
class Source:
    procedure: str
    version: str
    url: str


SOURCES: tuple[Source, ...] = (
    Source(
        "lumbar_spine_mri",
        "L37281",
        "https://www.cms.gov/medicare-coverage-database/view/lcd.aspx?lcdId=37281",
    ),
    Source(
        "knee_mri",
        "NCD-220.2",
        "https://www.cms.gov/medicare-coverage-database/view/ncd.aspx?ncdid=177",
    ),
    Source(
        "ct_abdomen",
        "L34415",
        "https://www.cms.gov/medicare-coverage-database/view/lcd.aspx?lcdId=34415",
    ),
)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip = 0
        self.chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if self._skip == 0 and data.strip():
            self.chunks.append(data.strip())


def _html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(parser.chunks))


_DATE_RE = re.compile(
    r"(?:Original )?Effective Date\D{0,160}?(\d{1,2}/\d{1,2}/\d{4})", re.IGNORECASE
)


def _effective_date(text: str) -> date | None:
    m = _DATE_RE.search(text)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%m/%d/%Y").date()
    except ValueError:
        return None


def _front_matter(src: Source, eff: date | None) -> str:
    return (
        "---\n"
        "payer: medicare\n"
        f"procedure: {src.procedure}\n"
        f"version: {src.version}\n"
        f"effective_from: {eff.isoformat() if eff else '2015-10-01'}\n"
        "effective_to:\n"
        f"source_url: {src.url}\n"
        "---\n"
    )


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    with httpx.Client(headers={"User-Agent": UA}, follow_redirects=True, timeout=45) as client:
        for src in SOURCES:
            resp = client.get(src.url)
            text = _html_to_text(resp.text)
            eff = _effective_date(text)
            out = RAW_DIR / f"{src.procedure}.md"
            out.write_text(_front_matter(src, eff) + "\n" + text + "\n")
            print(
                f"{src.procedure:18s} http={resp.status_code} "
                f"chars={len(text):6d} effective={eff} -> {out}"
            )


if __name__ == "__main__":
    main()
