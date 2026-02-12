"""
This module provides utilities for authenticating with and using the Gmail API.
"""

import base64
import json
import mimetypes
import os
import time
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import Resource, build
from googleapiclient.errors import HttpError

# Default settings
DEFAULT_CREDENTIALS_PATH = "credentials.json"
DEFAULT_TOKEN_PATH = "token.json"
DEFAULT_USER_ID = "me"

# Gmail API scopes (modify required for add/remove labels on messages)
GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.labels",
]

# For simpler testing
GMAIL_MODIFY_SCOPE = ["https://www.googleapis.com/auth/gmail.modify"]

# Type alias for the Gmail service
GmailService = Resource


def _execute_with_retry(request, max_retries: int = 3):
    """Execute a Gmail API request with retry on 429 (rate limit) and 5xx errors."""
    last_error = None
    for attempt in range(max_retries):
        try:
            return request.execute()
        except HttpError as e:
            last_error = e
            status = getattr(e, "resp", None) and getattr(e.resp, "status", None) or 0
            if status == 429 or (500 <= status < 600):
                if attempt < max_retries - 1:
                    time.sleep(2**attempt)
                    continue
            raise
    if last_error:
        raise last_error


def _is_legacy_token_format(data: Dict[str, Any]) -> bool:
    """True if data is a single OAuth token (has refresh_token at top level)."""
    return isinstance(data, dict) and "refresh_token" in data


def get_account_keys(token_path: str = DEFAULT_TOKEN_PATH) -> List[str]:
    """
    Return the list of account keys in the token file (for multi-account).
    If the file is legacy format or missing, return ["default"].
    """
    if not os.path.exists(token_path):
        return []
    with open(token_path, "r") as f:
        data = json.load(f)
    if _is_legacy_token_format(data):
        return ["default"]
    if isinstance(data, dict):
        return list(data.keys())
    return []


def _save_token_file(
    token_path: str,
    token_json: Dict[str, Any],
    account_key: str,
    is_multi: bool,
    existing_data: Optional[Dict[str, Any]] = None,
) -> None:
    """Save token. If is_multi or we're adding a second account, write multi-account format."""
    legacy_with_other = (
        existing_data is not None and _is_legacy_token_format(existing_data) and account_key != "default"
    )
    if is_multi or legacy_with_other:
        if os.path.exists(token_path):
            with open(token_path, "r") as f:
                data = json.load(f)
            if _is_legacy_token_format(data):
                data = {"default": data}
        else:
            data = {}
        data[account_key] = token_json
        with open(token_path, "w") as f:
            json.dump(data, f, indent=2)
    else:
        with open(token_path, "w") as f:
            json.dump(token_json, f, indent=2)


def get_gmail_service(
    credentials_path: str = DEFAULT_CREDENTIALS_PATH,
    token_path: str = DEFAULT_TOKEN_PATH,
    scopes: List[str] = GMAIL_SCOPES,
    account: Optional[str] = None,
) -> GmailService:
    """
    Authenticate with Gmail API and return the service object.

    Supports a single token file with multiple accounts: set account to the
    account key (e.g. "work") and use the same token_path for all accounts.
    The file will hold {"default": {...}, "work": {...}}. For one account,
    the file can be the legacy format (single token at root).

    Args:
        credentials_path: Path to the credentials JSON file
        token_path: Path to save/load the token (or multi-account token file)
        scopes: OAuth scopes to request
        account: Account key for multi-account single file (e.g. "work"). Omit for default.

    Returns:
        Authenticated Gmail API service
    """
    creds = None
    account_key = account or "default"
    existing_data = None
    is_multi_file = False

    if os.path.exists(token_path):
        with open(token_path, "r") as token:
            existing_data = json.load(token)
        if _is_legacy_token_format(existing_data):
            if account is None:
                creds = Credentials.from_authorized_user_info(existing_data)
        else:
            is_multi_file = True
            token_data = existing_data.get(account_key)
            if token_data:
                creds = Credentials.from_authorized_user_info(token_data)
            elif account is not None:
                available = ", ".join(sorted(existing_data.keys()))
                raise ValueError(
                    f"Account {account!r} not found in token file. "
                    f"Available: {available or 'none'}. "
                    "Run OAuth for the default account first, or use one of the listed keys."
                )

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(credentials_path):
                raise FileNotFoundError(
                    f"Credentials file not found at {credentials_path}. "
                    "Please download your OAuth credentials from Google Cloud Console."
                )
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, scopes)
            creds = flow.run_local_server(port=0)

        token_json = json.loads(creds.to_json())
        _save_token_file(token_path, token_json, account_key, is_multi_file, existing_data)

    return build("gmail", "v1", credentials=creds)


def create_message(
    sender: str,
    to: str,
    subject: str,
    message_text: str,
    cc: Optional[str] = None,
    bcc: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a message for the Gmail API.

    Args:
        sender: Email sender
        to: Email recipient
        subject: Email subject
        message_text: Email body text
        cc: Carbon copy recipients (optional)
        bcc: Blind carbon copy recipients (optional)

    Returns:
        A dictionary containing a base64url encoded email object
    """
    message = MIMEText(message_text)
    message["to"] = to
    message["from"] = sender
    message["subject"] = subject

    if cc:
        message["cc"] = cc
    if bcc:
        message["bcc"] = bcc

    # Encode the message
    encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()

    return {"raw": encoded_message}


def create_multipart_message(
    sender: str,
    to: str,
    subject: str,
    text_part: str,
    html_part: Optional[str] = None,
    cc: Optional[str] = None,
    bcc: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a multipart MIME message (text and HTML).

    Args:
        sender: Email sender
        to: Email recipient
        subject: Email subject
        text_part: Plain text email body
        html_part: HTML email body (optional)
        cc: Carbon copy recipients (optional)
        bcc: Blind carbon copy recipients (optional)

    Returns:
        A dictionary containing a base64url encoded email object
    """
    message = MIMEMultipart("alternative")
    message["to"] = to
    message["from"] = sender
    message["subject"] = subject

    if cc:
        message["cc"] = cc
    if bcc:
        message["bcc"] = bcc

    # Attach text part
    text_mime = MIMEText(text_part, "plain")
    message.attach(text_mime)

    # Attach HTML part if provided
    if html_part:
        html_mime = MIMEText(html_part, "html")
        message.attach(html_mime)

    # Encode the message
    encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()

    return {"raw": encoded_message}


def create_message_with_attachments(
    sender: str,
    to: str,
    subject: str,
    message_text: str,
    attachment_paths: Optional[List[Union[str, Path]]] = None,
    cc: Optional[str] = None,
    bcc: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a message with optional file attachments for the Gmail API.

    Args:
        sender: Email sender
        to: Email recipient
        subject: Email subject
        message_text: Email body text
        attachment_paths: Optional list of file paths to attach
        cc: Carbon copy recipients (optional)
        bcc: Blind carbon copy recipients (optional)

    Returns:
        A dictionary containing a base64url encoded email object
    """
    message = MIMEMultipart("mixed")
    message["to"] = to
    message["from"] = sender
    message["subject"] = subject

    if cc:
        message["cc"] = cc
    if bcc:
        message["bcc"] = bcc

    message.attach(MIMEText(message_text, "plain"))

    if attachment_paths:
        for path in attachment_paths:
            path = Path(path)
            if not path.exists():
                raise FileNotFoundError(f"Attachment not found: {path}")
            content_type, _ = mimetypes.guess_type(str(path))
            if content_type is None:
                content_type = "application/octet-stream"
            main_type, sub_type = content_type.split("/", 1)
            with open(path, "rb") as fp:
                part = MIMEBase(main_type, sub_type)
                part.set_payload(fp.read())
            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition",
                "attachment",
                filename=path.name,
            )
            message.attach(part)

    encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
    return {"raw": encoded_message}


def _parse_email_addresses(header_value: str) -> List[str]:
    """Parse a comma-separated email header into individual addresses."""
    if not header_value:
        return []
    return [addr.strip() for addr in header_value.split(",") if addr.strip()]


def _extract_email(address: str) -> str:
    """Extract bare email from 'Name <email>' format."""
    if "<" in address and ">" in address:
        return address[address.index("<") + 1 : address.index(">")].lower()
    return address.strip().lower()


def create_reply_message(
    service: GmailService,
    message_id: str,
    sender: str,
    body: str,
    user_id: str = DEFAULT_USER_ID,
    reply_all: bool = True,
    to: Optional[str] = None,
    cc: Optional[str] = None,
    bcc: Optional[str] = None,
    html_body: Optional[str] = None,
    attachment_paths: Optional[List[Union[str, Path]]] = None,
) -> Dict[str, Any]:
    """
    Create a reply message for an existing email, optionally with file attachments.

    Fetches the original message to get Message-ID, Subject, and threadId,
    then constructs a MIME message with proper In-Reply-To and References
    headers to keep the reply in the same Gmail thread.

    When reply_all=True (default), automatically includes all original To and
    CC recipients (excluding the sender's own email) in the CC field.

    If html_body is provided, creates a multipart/alternative message with
    both plain text and HTML parts. If attachment_paths is provided, uses
    multipart/mixed with body part(s) plus attachment parts.

    Args:
        service: Gmail API service instance
        message_id: The Gmail message ID to reply to
        sender: Email sender
        body: Reply body text (plain text)
        user_id: Gmail user ID (default: 'me')
        reply_all: If True, include all original recipients in CC (default: True)
        to: Override recipient (default: reply to original sender)
        cc: Additional CC recipients to merge with reply-all recipients (optional)
        bcc: Blind carbon copy recipients (optional)
        html_body: HTML version of the reply body (optional, creates multipart email)
        attachment_paths: Optional list of file paths to attach

    Returns:
        A dictionary containing a base64url encoded email object and threadId
    """
    original = get_message(service, message_id, user_id=user_id)
    headers = get_headers_dict(original)
    thread_id = original.get("threadId")

    original_message_id = headers.get("Message-ID", "")

    original_subject = headers.get("Subject", "")
    subject = original_subject if original_subject.startswith("Re:") else f"Re: {original_subject}"

    if to is None:
        to = headers.get("Reply-To", headers.get("From", ""))

    # Build CC list for reply-all
    if reply_all:
        sender_email = _extract_email(sender)
        to_email = _extract_email(to)

        # Collect all original To + CC recipients
        original_to = _parse_email_addresses(headers.get("To", ""))
        original_cc = _parse_email_addresses(headers.get("Cc", ""))
        all_recipients = original_to + original_cc

        # Filter out sender and the To recipient to avoid duplicates
        reply_all_cc = [
            addr for addr in all_recipients if _extract_email(addr) not in (sender_email, to_email)
        ]

        # Merge with any explicitly provided CC
        if cc:
            explicit_cc = _parse_email_addresses(cc)
            explicit_emails = {_extract_email(a) for a in explicit_cc}
            # Add reply-all addresses that aren't already in explicit CC
            for addr in reply_all_cc:
                if _extract_email(addr) not in explicit_emails:
                    explicit_cc.append(addr)
            cc = ", ".join(explicit_cc)
        elif reply_all_cc:
            cc = ", ".join(reply_all_cc)

    # Body part: plain, or alternative (plain + html)
    if html_body:
        body_part = MIMEMultipart("alternative")
        body_part.attach(MIMEText(body, "plain"))
        body_part.attach(MIMEText(html_body, "html"))
    else:
        body_part = MIMEText(body)

    # Root: use mixed when we have attachments so we can attach body + files
    if attachment_paths:
        message = MIMEMultipart("mixed")
        message.attach(body_part)
        for path in attachment_paths:
            path = Path(path)
            if not path.exists():
                raise FileNotFoundError(f"Attachment not found: {path}")
            content_type, _ = mimetypes.guess_type(str(path))
            if content_type is None:
                content_type = "application/octet-stream"
            main_type, sub_type = content_type.split("/", 1)
            with open(path, "rb") as fp:
                part = MIMEBase(main_type, sub_type)
                part.set_payload(fp.read())
            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition",
                "attachment",
                filename=path.name,
            )
            message.attach(part)
    else:
        message = body_part

    message["to"] = to
    message["from"] = sender
    message["subject"] = subject
    if cc:
        message["cc"] = cc
    if bcc:
        message["bcc"] = bcc
    if original_message_id:
        message["In-Reply-To"] = original_message_id
        message["References"] = original_message_id

    encoded = base64.urlsafe_b64encode(message.as_bytes()).decode()
    return {"raw": encoded, "threadId": thread_id}


def parse_message_body(message: Dict[str, Any]) -> str:
    """
    Parse the body of a Gmail message.

    Args:
        message: The Gmail message object

    Returns:
        The extracted message body text
    """

    # Helper function to find text/plain parts
    def get_text_part(parts):
        text = ""
        for part in parts:
            if part["mimeType"] == "text/plain":
                if "data" in part["body"]:
                    text += base64.urlsafe_b64decode(part["body"]["data"]).decode()
            elif "parts" in part:
                text += get_text_part(part["parts"])
        return text

    # Check if the message is multipart
    if "parts" in message["payload"]:
        return get_text_part(message["payload"]["parts"])
    else:
        # Handle single part messages
        if "data" in message["payload"]["body"]:
            data = message["payload"]["body"]["data"]
            return base64.urlsafe_b64decode(data).decode()
        return ""


def get_headers_dict(message: Dict[str, Any]) -> Dict[str, str]:
    """
    Extract headers from a Gmail message into a dictionary.

    Args:
        message: The Gmail message object (payload may be absent in minimal API responses)

    Returns:
        Dictionary of message headers
    """
    headers = {}
    payload = message.get("payload") if message else None
    if not payload or "headers" not in payload:
        return headers
    for header in payload["headers"]:
        headers[header["name"]] = header["value"]
    return headers


def send_email(
    service: GmailService,
    sender: str,
    to: str,
    subject: str,
    body: str,
    user_id: str = DEFAULT_USER_ID,
    cc: Optional[str] = None,
    bcc: Optional[str] = None,
    attachment_paths: Optional[List[Union[str, Path]]] = None,
) -> Dict[str, Any]:
    """
    Compose and send an email, optionally with file attachments.

    Args:
        service: Gmail API service instance
        sender: Email sender
        to: Email recipient
        subject: Email subject
        body: Email body text
        user_id: Gmail user ID (default: 'me')
        cc: Carbon copy recipients (optional)
        bcc: Blind carbon copy recipients (optional)
        attachment_paths: Optional list of file paths to attach

    Returns:
        Sent message object
    """
    if attachment_paths:
        message = create_message_with_attachments(
            sender, to, subject, body, attachment_paths=attachment_paths, cc=cc, bcc=bcc
        )
    else:
        message = create_message(sender, to, subject, body, cc, bcc)
    return _execute_with_retry(service.users().messages().send(userId=user_id, body=message))


def send_reply(
    service: GmailService,
    message_id: str,
    sender: str,
    body: str,
    user_id: str = DEFAULT_USER_ID,
    reply_all: bool = True,
    to: Optional[str] = None,
    cc: Optional[str] = None,
    bcc: Optional[str] = None,
    html_body: Optional[str] = None,
    attachment_paths: Optional[List[Union[str, Path]]] = None,
) -> Dict[str, Any]:
    """
    Send a reply to an existing email, keeping it in the same thread, optionally with attachments.

    Args:
        service: Gmail API service instance
        message_id: The Gmail message ID to reply to
        sender: Email sender
        body: Reply body text
        user_id: Gmail user ID (default: 'me')
        reply_all: If True, include all original recipients (default: True)
        to: Override recipient (default: reply to original sender)
        cc: Carbon copy recipients (optional)
        bcc: Blind carbon copy recipients (optional)
        html_body: HTML version of the reply body (optional)
        attachment_paths: Optional list of file paths to attach

    Returns:
        Sent message object
    """
    message = create_reply_message(
        service, message_id, sender, body, user_id, reply_all, to, cc, bcc, html_body, attachment_paths
    )
    return _execute_with_retry(service.users().messages().send(userId=user_id, body=message))


def get_labels(service: GmailService, user_id: str = DEFAULT_USER_ID) -> List[Dict[str, Any]]:
    """
    Get all labels for the specified user.

    Args:
        service: Gmail API service instance
        user_id: Gmail user ID (default: 'me')

    Returns:
        List of label objects
    """
    response = _execute_with_retry(service.users().labels().list(userId=user_id))
    return response.get("labels", [])


def list_messages(
    service: GmailService,
    user_id: str = DEFAULT_USER_ID,
    max_results: int = 10,
    query: Optional[str] = None,
    page_token: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """
    List messages in the user's mailbox.

    Args:
        service: Gmail API service instance
        user_id: Gmail user ID (default: 'me')
        max_results: Maximum number of messages to return (default: 10)
        query: Search query (default: None)
        page_token: Token for the next page of results (from a previous response)

    Returns:
        Tuple of (list of message objects, next_page_token or None)
    """
    request_params: Dict[str, Any] = {
        "userId": user_id,
        "maxResults": max_results,
        "q": query or "",
    }
    if page_token:
        request_params["pageToken"] = page_token
    response = _execute_with_retry(service.users().messages().list(**request_params))
    messages = response.get("messages", [])
    next_page_token = response.get("nextPageToken")
    return messages, next_page_token


def search_messages(
    service: GmailService,
    user_id: str = DEFAULT_USER_ID,
    max_results: int = 10,
    page_token: Optional[str] = None,
    is_unread: Optional[bool] = None,
    labels: Optional[List[str]] = None,
    from_email: Optional[str] = None,
    to_email: Optional[str] = None,
    subject: Optional[str] = None,
    after: Optional[str] = None,
    before: Optional[str] = None,
    has_attachment: Optional[bool] = None,
    is_starred: Optional[bool] = None,
    is_important: Optional[bool] = None,
    in_trash: Optional[bool] = None,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """
    Search for messages in the user's mailbox using various criteria.

    Args:
        service: Gmail API service instance
        user_id: Gmail user ID (default: 'me')
        max_results: Maximum number of messages to return (default: 10)
        page_token: Token for the next page (from a previous response)
        is_unread: If True, only return unread messages (optional)
        labels: List of label names to search for (optional)
        from_email: Sender email address (optional)
        to_email: Recipient email address (optional)
        subject: Subject text to search for (optional)
        after: Only return messages after this date (format: YYYY/MM/DD) (optional)
        before: Only return messages before this date (format: YYYY/MM/DD) (optional)
        has_attachment: If True, only return messages with attachments (optional)
        is_starred: If True, only return starred messages (optional)
        is_important: If True, only return important messages (optional)
        in_trash: If True, only search in trash (optional)

    Returns:
        Tuple of (list of message objects, next_page_token or None)
    """
    query_parts = []

    # Handle read/unread status
    if is_unread is not None:
        query_parts.append("is:unread" if is_unread else "")

    # Handle labels
    if labels:
        for label in labels:
            query_parts.append(f"label:{label}")

    # Handle from and to
    if from_email:
        query_parts.append(f"from:{from_email}")
    if to_email:
        query_parts.append(f"to:{to_email}")

    # Handle subject
    if subject:
        query_parts.append(f"subject:{subject}")

    # Handle date filters
    if after:
        query_parts.append(f"after:{after}")
    if before:
        query_parts.append(f"before:{before}")

    # Handle attachment filter
    if has_attachment is not None and has_attachment:
        query_parts.append("has:attachment")

    # Handle starred and important flags
    if is_starred is not None and is_starred:
        query_parts.append("is:starred")
    if is_important is not None and is_important:
        query_parts.append("is:important")

    # Handle trash
    if in_trash is not None and in_trash:
        query_parts.append("in:trash")

    # Join all query parts with spaces
    query = " ".join(query_parts)

    # Use the existing list_messages function to perform the search
    return list_messages(service, user_id, max_results, query, page_token=page_token)


def get_message(service: GmailService, message_id: str, user_id: str = DEFAULT_USER_ID) -> Dict[str, Any]:
    """
    Get a specific message by ID.

    Args:
        service: Gmail API service instance
        message_id: Gmail message ID
        user_id: Gmail user ID (default: 'me')

    Returns:
        Message object
    """
    message = _execute_with_retry(service.users().messages().get(userId=user_id, id=message_id))
    return message


def get_thread(service: GmailService, thread_id: str, user_id: str = DEFAULT_USER_ID) -> Dict[str, Any]:
    """
    Get a specific thread by ID.

    Args:
        service: Gmail API service instance
        thread_id: Gmail thread ID
        user_id: Gmail user ID (default: 'me')

    Returns:
        Thread object
    """
    thread = _execute_with_retry(service.users().threads().get(userId=user_id, id=thread_id))
    return thread


def create_draft(
    service: GmailService,
    sender: str,
    to: str,
    subject: str,
    body: str,
    user_id: str = DEFAULT_USER_ID,
    cc: Optional[str] = None,
    bcc: Optional[str] = None,
    attachment_paths: Optional[List[Union[str, Path]]] = None,
) -> Dict[str, Any]:
    """
    Create a draft email, optionally with file attachments.

    Args:
        service: Gmail API service instance
        sender: Email sender
        to: Email recipient
        subject: Email subject
        body: Email body text
        user_id: Gmail user ID (default: 'me')
        cc: Carbon copy recipients (optional)
        bcc: Blind carbon copy recipients (optional)
        attachment_paths: Optional list of file paths to attach

    Returns:
        Draft object
    """
    if attachment_paths:
        message = create_message_with_attachments(
            sender, to, subject, body, attachment_paths=attachment_paths, cc=cc, bcc=bcc
        )
    else:
        message = create_message(sender, to, subject, body, cc, bcc)
    draft_body = {"message": message}
    return service.users().drafts().create(userId=user_id, body=draft_body).execute()


def create_reply_draft(
    service: GmailService,
    message_id: str,
    sender: str,
    body: str,
    user_id: str = DEFAULT_USER_ID,
    reply_all: bool = True,
    to: Optional[str] = None,
    cc: Optional[str] = None,
    bcc: Optional[str] = None,
    html_body: Optional[str] = None,
    attachment_paths: Optional[List[Union[str, Path]]] = None,
) -> Dict[str, Any]:
    """
    Create a draft reply to an existing email, keeping it in the same thread, optionally with attachments.

    Args:
        service: Gmail API service instance
        message_id: The Gmail message ID to reply to
        sender: Email sender
        body: Reply body text
        user_id: Gmail user ID (default: 'me')
        reply_all: If True, include all original recipients (default: True)
        to: Override recipient (default: reply to original sender)
        cc: Carbon copy recipients (optional)
        bcc: Blind carbon copy recipients (optional)
        html_body: HTML version of the reply body (optional)
        attachment_paths: Optional list of file paths to attach

    Returns:
        Draft object
    """
    message = create_reply_message(
        service, message_id, sender, body, user_id, reply_all, to, cc, bcc, html_body, attachment_paths
    )
    draft_body = {"message": message}
    return service.users().drafts().create(userId=user_id, body=draft_body).execute()


def list_drafts(
    service: GmailService, user_id: str = DEFAULT_USER_ID, max_results: int = 10
) -> List[Dict[str, Any]]:
    """
    List draft emails in the user's mailbox.

    Args:
        service: Gmail API service instance
        user_id: Gmail user ID (default: 'me')
        max_results: Maximum number of drafts to return (default: 10)

    Returns:
        List of draft objects
    """
    response = service.users().drafts().list(userId=user_id, maxResults=max_results).execute()
    drafts = response.get("drafts", [])
    return drafts


def get_draft(service: GmailService, draft_id: str, user_id: str = DEFAULT_USER_ID) -> Dict[str, Any]:
    """
    Get a specific draft by ID.

    Args:
        service: Gmail API service instance
        draft_id: Gmail draft ID
        user_id: Gmail user ID (default: 'me')

    Returns:
        Draft object
    """
    draft = service.users().drafts().get(userId=user_id, id=draft_id).execute()
    return draft


def send_draft(service: GmailService, draft_id: str, user_id: str = DEFAULT_USER_ID) -> Dict[str, Any]:
    """
    Send an existing draft email.

    Args:
        service: Gmail API service instance
        draft_id: Gmail draft ID
        user_id: Gmail user ID (default: 'me')

    Returns:
        Sent message object
    """
    draft = {"id": draft_id}
    return _execute_with_retry(service.users().drafts().send(userId=user_id, body=draft))


def create_label(
    service: GmailService, name: str, user_id: str = DEFAULT_USER_ID, label_type: str = "user"
) -> Dict[str, Any]:
    """
    Create a new label.

    Args:
        service: Gmail API service instance
        name: Label name
        user_id: Gmail user ID (default: 'me')
        label_type: Label type (default: 'user')

    Returns:
        Created label object
    """
    label_body = {
        "name": name,
        "labelListVisibility": "labelShow",
        "messageListVisibility": "show",
        "type": label_type,
    }
    return service.users().labels().create(userId=user_id, body=label_body).execute()


def update_label(
    service: GmailService,
    label_id: str,
    name: Optional[str] = None,
    label_list_visibility: Optional[str] = None,
    message_list_visibility: Optional[str] = None,
    user_id: str = DEFAULT_USER_ID,
) -> Dict[str, Any]:
    """
    Update an existing label.

    Args:
        service: Gmail API service instance
        label_id: Label ID to update
        name: New label name (optional)
        label_list_visibility: Label visibility in label list (optional)
        message_list_visibility: Label visibility in message list (optional)
        user_id: Gmail user ID (default: 'me')

    Returns:
        Updated label object
    """
    # Get the current label to update
    label = service.users().labels().get(userId=user_id, id=label_id).execute()

    # Update fields if provided
    if name:
        label["name"] = name
    if label_list_visibility:
        label["labelListVisibility"] = label_list_visibility
    if message_list_visibility:
        label["messageListVisibility"] = message_list_visibility

    return service.users().labels().update(userId=user_id, id=label_id, body=label).execute()


def delete_label(service: GmailService, label_id: str, user_id: str = DEFAULT_USER_ID) -> None:
    """
    Delete a label.

    Args:
        service: Gmail API service instance
        label_id: Label ID to delete
        user_id: Gmail user ID (default: 'me')

    Returns:
        None
    """
    service.users().labels().delete(userId=user_id, id=label_id).execute()


def modify_message_labels(
    service: GmailService,
    message_id: str,
    add_labels: Optional[List[str]] = None,
    remove_labels: Optional[List[str]] = None,
    user_id: str = DEFAULT_USER_ID,
) -> Dict[str, Any]:
    """
    Modify the labels on a message.

    Args:
        service: Gmail API service instance
        message_id: Message ID
        add_labels: List of label IDs to add (optional)
        remove_labels: List of label IDs to remove (optional)
        user_id: Gmail user ID (default: 'me')

    Returns:
        Updated message object
    """
    body = {"addLabelIds": add_labels or [], "removeLabelIds": remove_labels or []}
    return service.users().messages().modify(userId=user_id, id=message_id, body=body).execute()


def batch_modify_messages_labels(
    service: GmailService,
    message_ids: List[str],
    add_labels: Optional[List[str]] = None,
    remove_labels: Optional[List[str]] = None,
    user_id: str = DEFAULT_USER_ID,
) -> None:
    """
    Batch modify the labels on multiple messages.

    Args:
        service: Gmail API service instance
        message_ids: List of message IDs
        add_labels: List of label IDs to add (optional)
        remove_labels: List of label IDs to remove (optional)
        user_id: Gmail user ID (default: 'me')

    Returns:
        None
    """
    body = {"ids": message_ids, "addLabelIds": add_labels or [], "removeLabelIds": remove_labels or []}
    service.users().messages().batchModify(userId=user_id, body=body).execute()


def trash_message(service: GmailService, message_id: str, user_id: str = DEFAULT_USER_ID) -> Dict[str, Any]:
    """
    Move a message to trash.

    Args:
        service: Gmail API service instance
        message_id: Message ID
        user_id: Gmail user ID (default: 'me')

    Returns:
        Updated message object
    """
    return service.users().messages().trash(userId=user_id, id=message_id).execute()


def untrash_message(
    service: GmailService, message_id: str, user_id: str = DEFAULT_USER_ID
) -> Dict[str, Any]:
    """
    Remove a message from trash.

    Args:
        service: Gmail API service instance
        message_id: Message ID
        user_id: Gmail user ID (default: 'me')

    Returns:
        Updated message object
    """
    return service.users().messages().untrash(userId=user_id, id=message_id).execute()


def _collect_attachment_parts(parts: List[Dict[str, Any]], acc: List[Dict[str, Any]]) -> None:
    """Recursively collect attachment part info (filename, attachment_id, mimeType, size)."""
    for part in parts or []:
        body = part.get("body") or {}
        attachment_id = body.get("attachmentId")
        filename = part.get("filename")
        if attachment_id or filename:
            acc.append(
                {
                    "filename": filename or "unnamed",
                    "attachment_id": attachment_id,
                    "mime_type": part.get("mimeType", "application/octet-stream"),
                    "size": body.get("size", 0),
                }
            )
        if "parts" in part:
            _collect_attachment_parts(part["parts"], acc)


def list_attachments(
    service: GmailService, message_id: str, user_id: str = DEFAULT_USER_ID
) -> List[Dict[str, Any]]:
    """
    List attachments for a message.

    Args:
        service: Gmail API service instance
        message_id: Gmail message ID
        user_id: Gmail user ID (default: 'me')

    Returns:
        List of dicts with filename, attachment_id, mime_type, size
    """
    message = _execute_with_retry(
        service.users().messages().get(userId=user_id, id=message_id, format="full")
    )
    payload = message.get("payload") or {}
    parts = payload.get("parts") or []
    if not parts and payload.get("filename"):
        body = payload.get("body") or {}
        return [
            {
                "filename": payload.get("filename", "unnamed"),
                "attachment_id": body.get("attachmentId"),
                "mime_type": payload.get("mimeType", "application/octet-stream"),
                "size": body.get("size", 0),
            }
        ]
    result: List[Dict[str, Any]] = []
    _collect_attachment_parts(parts, result)
    return result


def get_attachment(
    service: GmailService,
    user_id: str,
    message_id: str,
    attachment_id: str,
) -> bytes:
    """
    Get attachment content as bytes.

    Args:
        service: Gmail API service instance
        user_id: Gmail user ID
        message_id: Gmail message ID
        attachment_id: Gmail attachment ID

    Returns:
        Decoded attachment bytes
    """
    resp = (
        service.users()
        .messages()
        .attachments()
        .get(userId=user_id, messageId=message_id, id=attachment_id)
        .execute()
    )
    data = resp.get("data")
    if data:
        return base64.urlsafe_b64decode(data)
    return b""


def download_attachments(
    service: GmailService,
    message_id: str,
    target_dir: Union[str, Path],
    user_id: str = DEFAULT_USER_ID,
    download_all_in_thread: bool = False,
) -> List[Path]:
    """
    Download all attachments from a message (or its thread) to a directory.

    Args:
        service: Gmail API service instance
        message_id: Gmail message ID
        target_dir: Directory to save files into
        user_id: Gmail user ID (default: 'me')
        download_all_in_thread: If True, download attachments from every message in the thread

    Returns:
        List of paths to saved files
    """
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    saved: List[Path] = []
    message_ids_to_process: List[str] = [message_id]
    if download_all_in_thread:
        thread = get_thread(service, get_message(service, message_id, user_id)["threadId"], user_id)
        message_ids_to_process = [m["id"] for m in thread.get("messages", [])]
    for mid in message_ids_to_process:
        for att in list_attachments(service, mid, user_id):
            aid = att.get("attachment_id")
            if not aid:
                continue
            data = get_attachment(service, user_id, mid, aid)
            filename = att.get("filename") or "unnamed"
            path = target_dir / filename
            if path.exists():
                base, ext = path.stem, path.suffix
                n = 1
                while path.exists():
                    path = target_dir / f"{base}_{n}{ext}"
                    n += 1
            path.write_bytes(data)
            saved.append(path)
    return saved


def get_message_history(
    service: GmailService, history_id: str, user_id: str = DEFAULT_USER_ID, max_results: int = 100
) -> Dict[str, Any]:
    """
    Get history of changes to the mailbox.

    Args:
        service: Gmail API service instance
        history_id: Starting history ID
        user_id: Gmail user ID (default: 'me')
        max_results: Maximum number of history records to return

    Returns:
        History object
    """
    return (
        service.users()
        .history()
        .list(userId=user_id, startHistoryId=history_id, maxResults=max_results)
        .execute()
    )
