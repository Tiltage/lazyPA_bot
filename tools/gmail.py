"""Gmail tool functions."""
import base64
import logging
import re
from email.mime.text import MIMEText
from email.utils import parsedate_to_datetime
from config import GMAIL_DEFAULT_MAX_RESULTS, GMAIL_MAX_BODY_LENGTH, GMAIL_SNIPPET_LENGTH
from tools.utils import get_service

logger = logging.getLogger(__name__)


def _shorten_sender(from_str: str) -> str:
    """Extract a short display name or local-part from a From header."""
    match = re.match(r'^"?([^"<]+?)"?\s*<', from_str)
    if match:
        name = match.group(1).strip()
        if name:
            return name[:22]
    email_match = re.search(r'<([^>]+)>', from_str)
    if email_match:
        return email_match.group(1)[:22]
    return from_str[:22]


def _shorten_date(date_str: str) -> str:
    try:
        dt = parsedate_to_datetime(date_str)
        return dt.strftime("%b %d")
    except Exception:
        return date_str[:8] if date_str else ""


def _fetch_emails_raw(
    max_results: int = GMAIL_DEFAULT_MAX_RESULTS,
    query: str = "",
) -> list[dict]:
    """Fetch email metadata; returns list of structured dicts for UI use."""
    service = get_service("gmail", "v1")
    results = service.users().messages().list(
        userId="me", maxResults=max_results, q=query
    ).execute()
    messages = results.get("messages", [])
    emails = []
    for msg in messages:
        detail = service.users().messages().get(
            userId="me", id=msg["id"], format="metadata",
            metadataHeaders=["From", "Subject", "Date"],
        ).execute()
        headers = {h["name"]: h["value"] for h in detail["payload"]["headers"]}
        from_full = headers.get("From", "")
        date_full = headers.get("Date", "")
        emails.append({
            "id": msg["id"],
            "from": from_full,
            "from_short": _shorten_sender(from_full),
            "subject": headers.get("Subject", "(no subject)"),
            "date": date_full,
            "date_short": _shorten_date(date_full),
            "snippet": detail.get("snippet", "")[:GMAIL_SNIPPET_LENGTH],
        })
    return emails


def list_emails(max_results: int = GMAIL_DEFAULT_MAX_RESULTS, query: str = "") -> str:
    """List recent emails from Gmail inbox. Use query for filtering (e.g. 'from:boss@example.com', 'is:unread', 'subject:invoice')."""
    emails = _fetch_emails_raw(max_results, query)
    if not emails:
        result = "No emails found."
        logger.debug("[TOOL list_emails] query=%r max_results=%d => %s", query, max_results, result)
        return result
    output = []
    for e in emails:
        output.append(
            f"ID: {e['id']}\n"
            f"From: {e['from']}\n"
            f"Subject: {e['subject']}\n"
            f"Date: {e['date']}\n"
            f"Preview: {e['snippet']}"
        )
    result = "\n\n---\n\n".join(output)
    logger.debug("[TOOL list_emails] query=%r max_results=%d => %d emails:\n%s",
                 query, max_results, len(emails), result[:1000])
    return result


def get_emails_raw(
    max_results: int = GMAIL_DEFAULT_MAX_RESULTS,
    query: str = "",
) -> list[dict]:
    """Return structured email dicts for UI rendering (not for the LLM)."""
    return _fetch_emails_raw(max_results, query)


def get_email(message_id: str) -> str:
    """Get the full content of a specific email by its message ID."""
    service = get_service("gmail", "v1")
    msg = service.users().messages().get(
        userId="me", id=message_id, format="full"
    ).execute()
    headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
    body = ""
    parts = msg["payload"].get("parts", [])
    if parts:
        for part in parts:
            if part["mimeType"] == "text/plain":
                data = part["body"].get("data", "")
                body = base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
                break
    else:
        data = msg["payload"]["body"].get("data", "")
        body = base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
    result = (
        f"From: {headers.get('From', '')}\n"
        f"Subject: {headers.get('Subject', '')}\n"
        f"Date: {headers.get('Date', '')}\n\n"
        f"{body[:GMAIL_MAX_BODY_LENGTH]}"
    )
    logger.debug("[TOOL get_email] message_id=%r =>\n%s", message_id, result[:1000])
    return result


def send_email(to: str, subject: str, body: str) -> str:
    """Send an email via Gmail. Requires recipient address, subject, and body text."""
    service = get_service("gmail", "v1")
    msg = MIMEText(body)
    msg["to"] = to
    msg["subject"] = subject
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    service.users().messages().send(userId="me", body={"raw": raw}).execute()
    result = f"Email sent to {to} with subject '{subject}'."
    logger.debug("[TOOL send_email] to=%r subject=%r => %s", to, subject, result)
    return result
