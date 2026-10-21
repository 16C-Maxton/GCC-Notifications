import hashlib
import json
import os
import re
import smtplib
import sys
import time
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

BASE = "https://gcc.ac.in/"
STATE_FILE = Path("sent_notices.json")
MAX_PDF_BYTES = 20 * 1024 * 1024
TIMEOUT = 25

# Official GCC notification categories. These links were checked against the college website.
CATEGORY_PAGES = {
    "General Notifications": "https://gcc.ac.in/index_news_category.php?c=STFNSlY3dTRuVXpNQngxR2R6TEZwZz09",
    "Admission": "https://gcc.ac.in/index_news_category.php?c=ZHovaXUzdWdudkNUbUxOakNFSGVkQT09",
    "Recruitments": "https://gcc.ac.in/index_news_category.php?c=aTE1R29ZelFwY2FhR2tZR3FndW00dz09",
    "Tenders": "https://gcc.ac.in/index_news_category.php?c=QkVaMFBlSGJqNXE1U250cmp1aW55UT09",
    "Examinations": "https://gcc.ac.in/index_news_category.php?c=WXdWcnZrdzZKOVZBaTduTFM5d3JYdz09",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; GCC-Notice-Email-Monitor/1.0; educational personal use)"
}
DATE_RE = re.compile(
    r"(?:Posted\s*on\s*:?\s*)?(\d{1,2}\s+[A-Za-z]{3,9},?\s+\d{4}|\d{1,2}[/-]\d{1,2}[/-]\d{4})",
    re.I,
)


def clean_name(value: str) -> str:
    value = re.sub(r"[^\w\s.-]", "", value, flags=re.UNICODE)
    value = re.sub(r"\s+", "_", value.strip())
    return (value[:100] or "GCC_Notification") + ".pdf"


def notice_key(title: str, pdf_url: str) -> str:
    raw = f"{title.strip().lower()}|{pdf_url.strip()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def find_date(pdf_anchor) -> str:
    # The college page places the title, posted date and View PDF link close together.
    node = pdf_anchor
    for _ in range(5):
        if node is None:
            break
        text = node.get_text(" ", strip=True) if hasattr(node, "get_text") else ""
        match = DATE_RE.search(text)
        if match:
            return match.group(1)
        node = getattr(node, "parent", None)
    return "Date not shown"


def scrape_category(session: requests.Session, category: str, page_url: str):
    response = session.get(page_url, timeout=TIMEOUT)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    notices = []

    # On GCC category pages, each notice title is followed by a "View PDF" anchor.
    for pdf_anchor in soup.find_all("a"):
        label = " ".join(pdf_anchor.get_text(" ", strip=True).split()).lower()
        if label not in {"view pdf", "view file", "pdf"}:
            continue

        title_anchor = pdf_anchor.find_previous("a")
        if title_anchor is None:
            continue
        title = " ".join(title_anchor.get_text(" ", strip=True).split())
        pdf_url = urljoin(page_url, pdf_anchor.get("href", "").strip())
        title_url = urljoin(page_url, title_anchor.get("href", "").strip())

        if not title or not pdf_url or urlparse(pdf_url).scheme not in {"http", "https"}:
            continue
        # Avoid accidentally pairing a PDF link with a navigation item.
        if title.lower() in {"view all", "notifications", "admission", "examinations", "general notifications"}:
            continue

        key = notice_key(title, pdf_url)
        if any(n["key"] == key for n in notices):
            continue

        notices.append({
            "key": key,
            "title": title,
            "category": category,
            "date": find_date(pdf_anchor),
            "pdf_url": pdf_url,
            "notice_url": title_url,
        })

    return notices


def load_state():
    if not STATE_FILE.exists():
        return {"sent": []}
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("sent"), list):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return {"sent": []}


def save_state(state):
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def send_email(notice, pdf_bytes, filename):
    sender = os.environ["GMAIL_ADDRESS"].strip()
    app_password = os.environ["GMAIL_APP_PASSWORD"].replace(" ", "").strip()
    recipient = os.environ.get("RECIPIENT_EMAIL", sender).strip()

    msg = EmailMessage()
    msg["Subject"] = f"GCC Notification: {notice['title']}"
    msg["From"] = sender
    msg["To"] = recipient

    body = (
        "A new notification has been detected on the Gauhati Commerce College website.\n\n"
        f"Category: {notice['category']}\n"
        f"Title: {notice['title']}\n"
        f"Date shown on website: {notice['date']}\n\n"
        f"Direct PDF link: {notice['pdf_url']}\n"
        f"Notice page: {notice['notice_url']}\n\n"
        "The PDF is attached to this email."
    )
    msg.set_content(body)
    msg.add_attachment(pdf_bytes, maintype="application", subtype="pdf", filename=filename)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=TIMEOUT) as smtp:
        smtp.login(sender, app_password)
        smtp.send_message(msg)


def download_pdf(session, url):
    response = session.get(url, timeout=TIMEOUT, stream=True)
    response.raise_for_status()
    content_type = response.headers.get("Content-Type", "").lower()
    chunks = []
    total = 0
    for chunk in response.iter_content(chunk_size=64 * 1024):
        if not chunk:
            continue
        total += len(chunk)
        if total > MAX_PDF_BYTES:
            raise ValueError("PDF exceeds 20 MB safety limit")
        chunks.append(chunk)
    data = b"".join(chunks)
    if not data.startswith(b"%PDF") and "pdf" not in content_type:
        raise ValueError(f"Link did not return a PDF (Content-Type: {content_type or 'unknown'})")
    return data


def main():
    required = ["GMAIL_ADDRESS", "GMAIL_APP_PASSWORD"]
    missing = [name for name in required if not os.environ.get(name, "").strip()]
    if missing:
        print("Missing required environment variables: " + ", ".join(missing), file=sys.stderr)
        sys.exit(2)

    session = requests.Session()
    session.headers.update(HEADERS)

    found = []
    errors = []
    for category, url in CATEGORY_PAGES.items():
        try:
            notices = scrape_category(session, category, url)
            print(f"{category}: found {len(notices)} PDF-linked notices")
            found.extend(notices)
        except Exception as exc:
            errors.append(f"{category}: {exc}")
            print(f"ERROR while checking {category}: {exc}", file=sys.stderr)

    if not found:
        if errors:
            print("No notices parsed and some categories failed; state was not changed.")
            sys.exit(1)
        print("No PDF-linked notices found. Check website structure if this is unexpected.")
        sys.exit(0)

    state = load_state()
    known = set(state["sent"])

    # First run is a baseline only: it records existing notices without emailing old PDFs.
    if not known:
        state["sent"] = sorted({n["key"] for n in found})
        save_state(state)
        print(f"Baseline initialized with {len(state['sent'])} existing notices. No emails sent.")
        if errors:
            print("Some categories could not be checked: " + " | ".join(errors), file=sys.stderr)
        return

    new_notices = [n for n in found if n["key"] not in known]
    # Older notices are listed first if several were published between runs.
    new_notices.sort(key=lambda n: (n["date"], n["title"]))

    sent_keys = set(known)
    failed = []
    for notice in new_notices:
        try:
            pdf = download_pdf(session, notice["pdf_url"])
            send_email(notice, pdf, clean_name(notice["title"]))
            sent_keys.add(notice["key"])
            print(f"EMAIL SENT: {notice['title']}")
            time.sleep(1)
        except Exception as exc:
            failed.append(f"{notice['title']}: {exc}")
            print(f"ERROR sending {notice['title']}: {exc}", file=sys.stderr)

    # Do not mark a notice as sent unless its email was sent successfully.
    state["sent"] = sorted(sent_keys)
    save_state(state)

    if errors:
        print("Some categories could not be checked: " + " | ".join(errors), file=sys.stderr)
    if failed:
        print("Some new notices were not emailed: " + " | ".join(failed), file=sys.stderr)
        sys.exit(1)

    print(f"Finished. New notices emailed: {len(new_notices)}")


if __name__ == "__main__":
    main()
