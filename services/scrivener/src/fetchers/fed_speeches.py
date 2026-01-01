"""Federal Reserve speech fetcher.

Fetches speeches, statements, and press conferences from Federal Reserve websites.
"""

import logging
import re
from datetime import date, datetime
from io import BytesIO
from typing import Any

import httpx
from bs4 import BeautifulSoup
from PyPDF2 import PdfReader

from src.db import get_session
from src.db.models import Speaker, Speech

logger = logging.getLogger(__name__)


# Fed regional bank speech pages
FED_SPEECH_SOURCES = {
    "Board of Governors": "https://www.federalreserve.gov/newsevents/speeches.htm",
    "New York Fed": "https://www.newyorkfed.org/newsevents/speeches",
    "Chicago Fed": "https://www.chicagofed.org/publications/speeches",
    "San Francisco Fed": "https://www.frbsf.org/news-and-media/speeches/",
    "Dallas Fed": "https://www.dallasfed.org/news/speeches",
    "Atlanta Fed": "https://www.atlantafed.org/news/speeches",
    "Boston Fed": "https://www.bostonfed.org/news-and-events/speeches.aspx",
    "Cleveland Fed": "https://www.clevelandfed.org/collections/speeches",
    "Kansas City Fed": "https://www.kansascityfed.org/speeches/",
    "Minneapolis Fed": "https://www.minneapolisfed.org/speeches",
    "Philadelphia Fed": "https://www.philadelphiafed.org/the-economy/speeches",
    "Richmond Fed": "https://www.richmondfed.org/press_room/speeches",
    "St. Louis Fed": "https://www.stlouisfed.org/fomcspeak",
}

# Default Fed speakers (Board of Governors)
DEFAULT_FED_SPEAKERS = [
    ("Jerome H. Powell", "Chair", "Federal Reserve"),
    ("Philip N. Jefferson", "Vice Chair", "Federal Reserve"),
    ("Michael S. Barr", "Vice Chair for Supervision", "Federal Reserve"),
    ("Michelle W. Bowman", "Governor", "Federal Reserve"),
    ("Lisa D. Cook", "Governor", "Federal Reserve"),
    ("Adriana D. Kugler", "Governor", "Federal Reserve"),
    ("Christopher J. Waller", "Governor", "Federal Reserve"),
]


class FedSpeechFetcher:
    """Fetcher for Federal Reserve speeches and communications."""

    def __init__(self):
        self.client = httpx.Client(timeout=30, follow_redirects=True)

    def fetch_text_from_url(self, url: str) -> tuple[str, str]:
        """
        Fetch and extract text from a speech URL (HTML or PDF).

        Args:
            url: URL of the speech

        Returns:
            Tuple of (extracted_text, content_type)
        """
        response = self.client.get(url)
        response.raise_for_status()

        content_type = response.headers.get("Content-Type", "")

        # Handle PDF
        if url.endswith(".pdf") or "application/pdf" in content_type:
            return self._extract_pdf_text(response.content), "pdf"

        # Handle HTML
        return self._extract_html_text(response.content), "html"

    def _extract_pdf_text(self, content: bytes) -> str:
        """Extract text from PDF content."""
        pdf_reader = PdfReader(BytesIO(content))
        text_parts = []

        for page in pdf_reader.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)

        text = "\n\n".join(text_parts)

        # Clean up PDF text
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        return "\n\n".join(lines)

    def _extract_html_text(self, content: bytes) -> str:
        """Extract speech text from HTML content."""
        soup = BeautifulSoup(content, "html.parser")

        # Remove non-content elements
        for element in soup(["script", "style", "nav", "footer", "header", "aside"]):
            element.decompose()

        all_text = soup.get_text()
        lines = [line.strip() for line in all_text.split("\n") if line.strip()]

        # Find actual speech content using heuristics
        content_lines = []
        in_content = False

        for i, line in enumerate(lines):
            # Speech typically starts with greeting or long paragraph
            if not in_content and (
                "Thank you" in line
                or "Good morning" in line
                or "Good afternoon" in line
                or "Good evening" in line
                or (i > 0 and len(line) > 100)
            ):
                in_content = True

            # Stop at footer markers
            if in_content and (
                "Last Update" in line
                or "Back to Top" in line
                or "Return to text" in line
            ):
                break

            # Collect content lines (filter short navigation items)
            if in_content and len(line) > 20:
                content_lines.append(line)

        text = "\n\n".join(content_lines)

        # Fallback to all paragraphs if not enough content
        if len(text) < 500:
            paragraphs = soup.find_all("p")
            text = "\n\n".join(
                [
                    p.get_text().strip()
                    for p in paragraphs
                    if p.get_text().strip() and len(p.get_text().strip()) > 20
                ]
            )

        return text

    def get_or_create_speaker(
        self, name: str, title: str | None = None, institution: str = "Federal Reserve"
    ) -> int:
        """Get or create a speaker record."""
        with get_session() as session:
            speaker = session.query(Speaker).filter(Speaker.name == name).first()

            if not speaker:
                speaker = Speaker(
                    name=name,
                    title=title,
                    institution=institution,
                )
                session.add(speaker)
                session.commit()
                logger.info(f"Created speaker: {name}")

            return speaker.id

    def speech_exists(self, url: str) -> bool:
        """Check if a speech URL has already been stored."""
        with get_session() as session:
            return session.query(Speech).filter(Speech.url == url).first() is not None

    def fetch_and_store(
        self,
        url: str,
        speaker_name: str,
        speech_date: date,
        title: str | None = None,
        speech_type: str = "speech",
        source: str = "Federal Reserve",
    ) -> dict[str, Any]:
        """
        Fetch a speech and store it in the database.

        Args:
            url: URL of the speech
            speaker_name: Name of the speaker
            speech_date: Date of the speech
            title: Optional title
            speech_type: Type (speech, statement, press_conference)
            source: Source institution

        Returns:
            Result dict with status and details
        """
        if self.speech_exists(url):
            return {
                "status": "skipped",
                "url": url,
                "reason": "already_exists",
            }

        try:
            logger.info(f"Fetching speech: {url}")
            raw_text, content_type = self.fetch_text_from_url(url)

            if not raw_text or len(raw_text) < 100:
                return {
                    "status": "error",
                    "url": url,
                    "error": "Insufficient text extracted",
                }

            # Get or create speaker
            speaker_id = self.get_or_create_speaker(speaker_name, institution=source)

            # Store speech
            with get_session() as session:
                speech = Speech(
                    url=url,
                    speaker_id=speaker_id,
                    speaker_name=speaker_name,
                    title=title,
                    speech_date=speech_date,
                    speech_type=speech_type,
                    source=source,
                    content_type=content_type,
                    raw_text=raw_text,
                    word_count=len(raw_text.split()),
                )
                session.add(speech)
                session.commit()

                logger.info(
                    f"Stored speech: {speaker_name} ({speech_date}) - {len(raw_text)} chars"
                )

                return {
                    "status": "success",
                    "url": url,
                    "speaker": speaker_name,
                    "date": speech_date.isoformat(),
                    "word_count": speech.word_count,
                    "content_type": content_type,
                }

        except Exception as e:
            logger.error(f"Error fetching speech {url}: {e}")
            return {
                "status": "error",
                "url": url,
                "error": str(e),
            }

    def seed_default_speakers(self) -> int:
        """Seed the database with default Fed speakers."""
        count = 0
        for name, title, institution in DEFAULT_FED_SPEAKERS:
            with get_session() as session:
                existing = session.query(Speaker).filter(Speaker.name == name).first()
                if not existing:
                    speaker = Speaker(name=name, title=title, institution=institution)
                    session.add(speaker)
                    session.commit()
                    count += 1
                    logger.info(f"Seeded speaker: {name}")
        return count

    def scrape_fed_speeches_listing(
        self, days_back: int = 30
    ) -> list[dict[str, Any]]:
        """
        Scrape the Fed Board of Governors speeches listing page.

        Args:
            days_back: How many days of speeches to look for

        Returns:
            List of speech metadata dicts
        """
        url = FED_SPEECH_SOURCES["Board of Governors"]
        speeches = []

        try:
            response = self.client.get(url)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, "html.parser")

            # Find speech entries (structure may vary)
            # This is a basic implementation - may need adjustment based on actual page structure
            for item in soup.select(".row.ng-cloak"):
                try:
                    link = item.select_one("a")
                    if not link:
                        continue

                    speech_url = link.get("href", "")
                    if not speech_url.startswith("http"):
                        speech_url = "https://www.federalreserve.gov" + speech_url

                    title = link.get_text(strip=True)

                    # Extract date if available
                    date_elem = item.select_one(".news__date, .eventlist__date, time")
                    speech_date = None
                    if date_elem:
                        date_text = date_elem.get_text(strip=True)
                        # Parse date (format varies)
                        try:
                            speech_date = datetime.strptime(
                                date_text, "%B %d, %Y"
                            ).date()
                        except ValueError:
                            pass

                    # Extract speaker if available
                    speaker_elem = item.select_one(".news__speaker, .speaker")
                    speaker_name = (
                        speaker_elem.get_text(strip=True) if speaker_elem else None
                    )

                    speeches.append(
                        {
                            "url": speech_url,
                            "title": title,
                            "date": speech_date,
                            "speaker": speaker_name,
                        }
                    )
                except Exception as e:
                    logger.warning(f"Error parsing speech entry: {e}")
                    continue

        except Exception as e:
            logger.error(f"Error scraping speeches listing: {e}")

        return speeches

    def close(self):
        """Close the HTTP client."""
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
