"""
Gmail MCP Server Implementation

This module provides a Model Context Protocol server for interacting with Gmail.
It exposes Gmail messages as resources and provides tools for composing and sending emails.
"""

import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from mcp.server.fastmcp import FastMCP

from mcp_gmail.config import get_token_path_for_account, settings
from mcp_gmail.gmail import (
    batch_modify_messages_labels,
    create_draft,
    create_label as gmail_create_label,
    create_reply_draft,
    delete_label as gmail_delete_label,
    download_attachments,
    get_draft as gmail_get_draft,
    get_gmail_service,
    get_headers_dict,
    get_labels,
    get_message,
    get_thread,
    list_attachments as gmail_list_attachments,
    list_drafts as gmail_list_drafts,
    list_messages,
    modify_message_labels,
    parse_message_body,
    search_messages,
    send_draft as gmail_send_draft,
    send_reply,
    trash_message as gmail_trash_message,
    untrash_message as gmail_untrash_message,
    update_label as gmail_update_label,
)
from mcp_gmail.gmail import send_email as gmail_send_email

# Lazy-initialize Gmail service per account so MCP handshake completes before any auth/network calls
_services: dict = {}


def get_service(account: Optional[str] = None):
    """Return Gmail service for default or given account (multi-account support)."""
    key = account or "__default__"
    if key not in _services:
        token_path = get_token_path_for_account(account)
        _services[key] = get_gmail_service(
            credentials_path=settings.credentials_path,
            token_path=token_path,
            scopes=settings.scopes,
            account=account if settings.multi_account_single_file else None,
        )
    return _services[key]


mcp = FastMCP(
    "Gmail MCP Server",
    instructions="""Access and interact with Gmail. You can get messages, threads, search emails, send or compose messages (with optional attachments), reply to emails (with optional attachments via reply_to_email), manage drafts and labels, trash/untrash, and download attachments. Multi-account is supported via the optional 'account' parameter on tools (use token file suffix, e.g. token_work.json for account 'work').

For token-efficient or scripted workflows (e.g. a skill, cron job, or one-off script), prefer writing a Python script that calls the same logic directly instead of using MCP tool calls. Same OAuth setup (credentials.json, token.json). Example:

  from mcp_gmail.gmail import (
    get_gmail_service, send_email, search_messages, get_message,
    get_headers_dict, parse_message_body,
  )
  service = get_gmail_service(credentials_path="credentials.json", token_path="token.json")
  # Then e.g. send_email(service, ...), search_messages(service, ...), get_message(service, msg_id)
""",
)

EMAIL_PREVIEW_LENGTH = 200


# Helper functions
def format_message(message):
    """Format a Gmail message for display."""
    headers = get_headers_dict(message)
    body = parse_message_body(message)

    # Extract relevant headers
    from_header = headers.get("From", "Unknown")
    to_header = headers.get("To", "Unknown")
    subject = headers.get("Subject", "No Subject")
    date = headers.get("Date", "Unknown Date")

    return f"""
From: {from_header}
To: {to_header}
Subject: {subject}
Date: {date}

{body}
"""


def validate_date_format(date_str):
    """
    Validate that a date string is in the format YYYY/MM/DD.

    Args:
        date_str: The date string to validate

    Returns:
        bool: True if valid, False otherwise
    """
    if not date_str:
        return True

    # Check format with regex
    if not re.match(r"^\d{4}/\d{2}/\d{2}$", date_str):
        return False

    # Validate the date is a real date
    try:
        datetime.strptime(date_str, "%Y/%m/%d")
        return True
    except ValueError:
        return False


# Resources
@mcp.resource("gmail://messages/{message_id}")
def get_email_message(message_id: str) -> str:
    """
    Get the content of an email message by its ID.

    Args:
        message_id: The Gmail message ID

    Returns:
        The formatted email content
    """
    message = get_message(get_service(), message_id, user_id=settings.user_id)
    formatted_message = format_message(message)
    return formatted_message


@mcp.resource("gmail://threads/{thread_id}")
def get_email_thread(thread_id: str) -> str:
    """
    Get all messages in an email thread by thread ID.

    Args:
        thread_id: The Gmail thread ID

    Returns:
        The formatted thread content with all messages
    """
    thread = get_thread(get_service(), thread_id, user_id=settings.user_id)
    messages = thread.get("messages", [])

    result = f"Email Thread (ID: {thread_id})\n"
    for i, message in enumerate(messages, 1):
        result += f"\n--- Message {i} ---\n"
        result += format_message(message)

    return result


@mcp.resource("gmail://inbox")
def get_inbox() -> str:
    """
    Get latest emails from the inbox (default account).

    Returns:
        Formatted list of recent inbox messages
    """
    messages, next_page_token = list_messages(
        get_service(),
        user_id=settings.user_id,
        max_results=settings.max_results,
        query="in:inbox",
    )
    result = f"Inbox (latest {len(messages)} messages):\n"
    if next_page_token:
        result += f"next_page_token: {next_page_token}\n"
    for msg_info in messages:
        msg_id = msg_info.get("id")
        message = get_message(get_service(), msg_id, user_id=settings.user_id)
        headers = get_headers_dict(message)
        result += f"\nMessage ID: {msg_id}\n"
        result += f"From: {headers.get('From', 'Unknown')}\n"
        result += f"Subject: {headers.get('Subject', 'No Subject')}\n"
        result += f"Date: {headers.get('Date', 'Unknown')}\n"
    return result


@mcp.resource("gmail://inbox/{account}")
def get_inbox_for_account(account: str) -> str:
    """
    Get latest emails from the inbox for a specific account.

    Args:
        account: Account identifier (token file suffix, e.g. work for token_work.json)

    Returns:
        Formatted list of recent inbox messages
    """
    messages, next_page_token = list_messages(
        get_service(account),
        user_id=settings.user_id,
        max_results=settings.max_results,
        query="in:inbox",
    )
    result = f"Inbox for account '{account}' (latest {len(messages)} messages):\n"
    if next_page_token:
        result += f"next_page_token: {next_page_token}\n"
    for msg_info in messages:
        msg_id = msg_info.get("id")
        message = get_message(get_service(account), msg_id, user_id=settings.user_id)
        headers = get_headers_dict(message)
        result += f"\nMessage ID: {msg_id}\n"
        result += f"From: {headers.get('From', 'Unknown')}\n"
        result += f"Subject: {headers.get('Subject', 'No Subject')}\n"
        result += f"Date: {headers.get('Date', 'Unknown')}\n"
    return result


# Tools
@mcp.tool()
def compose_email(
    to: str,
    subject: str,
    body: str,
    cc: Optional[str] = None,
    bcc: Optional[str] = None,
    attachment_paths: Optional[List[str]] = None,
    account: Optional[str] = None,
) -> str:
    """
    Compose a new email draft, optionally with file attachments.

    Args:
        to: Recipient email address
        subject: Email subject
        body: Email body content
        cc: Carbon copy recipients (optional)
        bcc: Blind carbon copy recipients (optional)
        attachment_paths: Optional list of file paths to attach
        account: Account identifier for multi-account (optional)

    Returns:
        The ID of the created draft and its content
    """
    svc = get_service(account)
    sender = svc.users().getProfile(userId=settings.user_id).execute().get("emailAddress")
    draft = create_draft(
        svc,
        sender=sender,
        to=to,
        subject=subject,
        body=body,
        user_id=settings.user_id,
        cc=cc,
        bcc=bcc,
        attachment_paths=attachment_paths,
    )

    draft_id = draft.get("id")
    return f"""
Email draft created with ID: {draft_id}
To: {to}
Subject: {subject}
CC: {cc or ""}
BCC: {bcc or ""}
Attachments: {len(attachment_paths or [])} file(s)
Body: {body[:EMAIL_PREVIEW_LENGTH]}{"..." if len(body) > EMAIL_PREVIEW_LENGTH else ""}
"""


@mcp.tool()
def send_email(
    to: str,
    subject: str,
    body: str,
    cc: Optional[str] = None,
    bcc: Optional[str] = None,
    attachment_paths: Optional[List[str]] = None,
    account: Optional[str] = None,
) -> str:
    """
    Compose and send an email, optionally with file attachments.

    Args:
        to: Recipient email address
        subject: Email subject
        body: Email body content
        cc: Carbon copy recipients (optional)
        bcc: Blind carbon copy recipients (optional)
        attachment_paths: Optional list of file paths to attach
        account: Account identifier for multi-account (optional)

    Returns:
        Content of the sent email
    """
    svc = get_service(account)
    sender = svc.users().getProfile(userId=settings.user_id).execute().get("emailAddress")
    message = gmail_send_email(
        svc,
        sender=sender,
        to=to,
        subject=subject,
        body=body,
        user_id=settings.user_id,
        cc=cc,
        bcc=bcc,
        attachment_paths=attachment_paths,
    )

    message_id = message.get("id")
    return f"""
Email sent successfully with ID: {message_id}
To: {to}
Subject: {subject}
CC: {cc or ""}
BCC: {bcc or ""}
Attachments: {len(attachment_paths or [])} file(s)
Body: {body[:EMAIL_PREVIEW_LENGTH]}{"..." if len(body) > EMAIL_PREVIEW_LENGTH else ""}
"""


@mcp.tool()
def reply_to_email(
    message_id: str,
    body: str,
    reply_all: bool = True,
    to: Optional[str] = None,
    cc: Optional[str] = None,
    bcc: Optional[str] = None,
    html_body: Optional[str] = None,
    attachment_paths: Optional[List[str]] = None,
    send: bool = False,
    account: Optional[str] = None,
) -> str:
    """
    Reply to an existing email, keeping the reply in the same thread.

    By default creates a draft with reply-all (includes all original recipients).
    Set reply_all=False to reply only to the sender.
    Set send=True to send immediately.
    Provide html_body for rich formatting (tables, bold, etc.).
    Provide attachment_paths to attach files to the reply.

    Args:
        message_id: The Gmail message ID to reply to
        body: Reply body content (plain text)
        reply_all: If True, include all original To/CC recipients (default: True)
        to: Override recipient (default: reply to sender)
        cc: Additional CC recipients to merge with reply-all recipients (optional)
        bcc: Blind carbon copy recipients (optional)
        html_body: HTML version of the body for rich formatting (optional)
        attachment_paths: Optional list of file paths to attach to the reply
        send: If True, send immediately; if False, create draft (default: False)
        account: Account identifier for multi-account (optional)

    Returns:
        Confirmation with draft/message ID and details
    """
    svc = get_service(account)
    sender = svc.users().getProfile(userId=settings.user_id).execute().get("emailAddress")

    # Get original message details for display
    original = get_message(svc, message_id, user_id=settings.user_id)
    original_headers = get_headers_dict(original)
    original_subject = original_headers.get("Subject", "No Subject")
    reply_to = to or original_headers.get("Reply-To", original_headers.get("From", ""))

    if send:
        result = send_reply(
            svc,
            message_id=message_id,
            sender=sender,
            body=body,
            user_id=settings.user_id,
            reply_all=reply_all,
            to=to,
            cc=cc,
            bcc=bcc,
            html_body=html_body,
            attachment_paths=attachment_paths,
        )
        result_id = result.get("id")
        return f"""
Reply sent successfully with ID: {result_id}
In reply to: {original_subject}
To: {reply_to}
CC: {cc or "(none)"}
Reply-All: {reply_all}
Attachments: {len(attachment_paths or [])} file(s)
Body: {body[:EMAIL_PREVIEW_LENGTH]}{"..." if len(body) > EMAIL_PREVIEW_LENGTH else ""}
"""
    else:
        result = create_reply_draft(
            svc,
            message_id=message_id,
            sender=sender,
            body=body,
            user_id=settings.user_id,
            reply_all=reply_all,
            to=to,
            cc=cc,
            bcc=bcc,
            html_body=html_body,
            attachment_paths=attachment_paths,
        )
        draft_id = result.get("id")
        return f"""
Reply draft created with ID: {draft_id}
In reply to: {original_subject}
To: {reply_to}
CC: {cc or "(none)"}
Reply-All: {reply_all}
Attachments: {len(attachment_paths or [])} file(s)
Body: {body[:EMAIL_PREVIEW_LENGTH]}{"..." if len(body) > EMAIL_PREVIEW_LENGTH else ""}
"""


@mcp.tool()
def search_emails(
    from_email: Optional[str] = None,
    to_email: Optional[str] = None,
    subject: Optional[str] = None,
    has_attachment: bool = False,
    is_unread: bool = False,
    after_date: Optional[str] = None,
    before_date: Optional[str] = None,
    label: Optional[str] = None,
    max_results: int = 10,
    page_token: Optional[str] = None,
    include_conversations: bool = False,
    account: Optional[str] = None,
) -> str:
    """
    Search for emails using specific search criteria.

    Args:
        from_email: Filter by sender email
        to_email: Filter by recipient email
        subject: Filter by subject text
        has_attachment: Filter for emails with attachments
        is_unread: Filter for unread emails
        after_date: Filter for emails after this date (format: YYYY/MM/DD)
        before_date: Filter for emails before this date (format: YYYY/MM/DD)
        label: Filter by Gmail label
        max_results: Maximum number of results to return
        page_token: Token for the next page (omit for first page; use next_page_token from previous response)
        include_conversations: If True, include thread context (other messages in same thread) for each result
        account: Account identifier for multi-account (optional)

    Returns:
        Formatted list of matching emails. Includes next_page_token when more results are available.
    """
    # Validate date formats
    if after_date and not validate_date_format(after_date):
        return f"Error: after_date '{after_date}' is not in the required format YYYY/MM/DD"

    if before_date and not validate_date_format(before_date):
        return f"Error: before_date '{before_date}' is not in the required format YYYY/MM/DD"

    svc = get_service(account)
    messages, next_page_token = search_messages(
        svc,
        user_id=settings.user_id,
        from_email=from_email,
        to_email=to_email,
        subject=subject,
        has_attachment=has_attachment,
        is_unread=is_unread,
        after=after_date,
        before=before_date,
        labels=[label] if label else None,
        max_results=max_results,
        page_token=page_token,
    )

    result = f"Found {len(messages)} messages matching criteria:\n"
    if next_page_token:
        result += f"next_page_token: {next_page_token}\n"

    for msg_info in messages:
        msg_id = msg_info.get("id")
        thread_id = msg_info.get("threadId")
        message = get_message(svc, msg_id, user_id=settings.user_id)
        headers = get_headers_dict(message)

        from_header = headers.get("From", "Unknown")
        subj = headers.get("Subject", "No Subject")
        date = headers.get("Date", "Unknown Date")

        result += f"\nMessage ID: {msg_id}\n"
        result += f"Thread ID: {thread_id}\n"
        result += f"From: {from_header}\n"
        result += f"Subject: {subj}\n"
        result += f"Date: {date}\n"
        if include_conversations and thread_id:
            thread = get_thread(svc, thread_id, user_id=settings.user_id)
            others = [m for m in thread.get("messages", []) if m.get("id") != msg_id]
            if others:
                result += f"  Thread has {len(others)} other message(s). Use get_email_thread(thread_id={thread_id}) for full thread.\n"

    return result


@mcp.tool()
def query_emails(
    query: str,
    max_results: int = 10,
    page_token: Optional[str] = None,
    account: Optional[str] = None,
) -> str:
    """
    Search for emails using a raw Gmail query string.

    Args:
        query: Gmail search query (same syntax as Gmail search box)
        max_results: Maximum number of results to return
        page_token: Token for the next page (omit for first page; use next_page_token from previous response)
        account: Account identifier for multi-account (optional)

    Returns:
        Formatted list of matching emails. Includes next_page_token when more results are available.
    """
    svc = get_service(account)
    messages, next_page_token = list_messages(
        svc,
        user_id=settings.user_id,
        max_results=max_results,
        query=query,
        page_token=page_token,
    )

    result = f'Found {len(messages)} messages matching query: "{query}"\n'
    if next_page_token:
        result += f"next_page_token: {next_page_token}\n"

    for msg_info in messages:
        msg_id = msg_info.get("id")
        message = get_message(svc, msg_id, user_id=settings.user_id)
        headers = get_headers_dict(message)

        from_header = headers.get("From", "Unknown")
        subj = headers.get("Subject", "No Subject")
        date = headers.get("Date", "Unknown Date")

        result += f"\nMessage ID: {msg_id}\n"
        result += f"From: {from_header}\n"
        result += f"Subject: {subj}\n"
        result += f"Date: {date}\n"

    return result


@mcp.tool()
def read_latest_emails(
    max_results: int = 10,
    download_attachments_flag: bool = False,
    target_dir: Optional[str] = None,
    account: Optional[str] = None,
) -> str:
    """
    Read the latest emails from the inbox (by internal date).

    Args:
        max_results: Maximum number of emails to return (default 10)
        download_attachments_flag: If True, download attachments to target_dir
        target_dir: Directory to save attachments (default: downloaded_attachments); used when download_attachments_flag is True
        account: Account identifier for multi-account (optional)

    Returns:
        Formatted list of latest emails; if download_attachments_flag is True, includes paths to saved files
    """
    svc = get_service(account)
    messages, _ = list_messages(
        svc,
        user_id=settings.user_id,
        max_results=max_results,
        query="in:inbox",
    )
    result = f"Latest {len(messages)} inbox messages:\n"
    download_dir = Path(target_dir or "downloaded_attachments")
    for msg_info in messages:
        msg_id = msg_info.get("id")
        message = get_message(svc, msg_id, user_id=settings.user_id)
        result += f"\n--- Message ID: {msg_id} ---\n"
        result += format_message(message)
        if download_attachments_flag:
            atts = gmail_list_attachments(svc, msg_id, settings.user_id)
            if atts:
                saved = download_attachments(
                    svc, msg_id, download_dir, user_id=settings.user_id, download_all_in_thread=False
                )
                result += f"  Attachments downloaded ({len(saved)} file(s)) to: {download_dir}\n"
    return result


@mcp.tool()
def list_available_labels(account: Optional[str] = None) -> str:
    """
    Get all available Gmail labels for the user.

    Args:
        account: Account identifier for multi-account (optional)

    Returns:
        Formatted list of labels with their IDs
    """
    labels = get_labels(get_service(account), user_id=settings.user_id)

    result = "Available Gmail Labels:\n"
    for label in labels:
        label_id = label.get("id", "Unknown")
        name = label.get("name", "Unknown")
        type_info = label.get("type", "user")

        result += f"\nLabel ID: {label_id}\n"
        result += f"Name: {name}\n"
        result += f"Type: {type_info}\n"

    return result


@mcp.tool()
def mark_message_read(message_id: str, account: Optional[str] = None) -> str:
    """
    Mark a message as read by removing the UNREAD label.

    Args:
        message_id: The Gmail message ID to mark as read
        account: Account identifier for multi-account (optional)

    Returns:
        Confirmation message
    """
    svc = get_service(account)
    result = modify_message_labels(
        svc, user_id=settings.user_id, message_id=message_id, remove_labels=["UNREAD"], add_labels=[]
    )

    subject = "No Subject"
    if result and "payload" in result:
        headers = get_headers_dict(result)
        subject = headers.get("Subject", "No Subject")

    return f"""
Message marked as read:
ID: {message_id}
Subject: {subject}
"""


@mcp.tool()
def add_label_to_message(message_id: str, label_id: str, account: Optional[str] = None) -> str:
    """
    Add a label to a message.

    Args:
        message_id: The Gmail message ID
        label_id: The Gmail label ID to add (use list_available_labels to find label IDs)
        account: Account identifier for multi-account (optional)

    Returns:
        Confirmation message
    """
    svc = get_service(account)
    result = modify_message_labels(
        svc, user_id=settings.user_id, message_id=message_id, remove_labels=[], add_labels=[label_id]
    )

    subject = "No Subject"
    if result and "payload" in result:
        headers = get_headers_dict(result)
        subject = headers.get("Subject", "No Subject")

    label_name = label_id
    labels = get_labels(svc, user_id=settings.user_id)
    for label in labels:
        if label.get("id") == label_id:
            label_name = label.get("name", label_id)
            break

    return f"""
Label added to message:
ID: {message_id}
Subject: {subject}
Added Label: {label_name} ({label_id})
"""


@mcp.tool()
def remove_label_from_message(message_id: str, label_id: str, account: Optional[str] = None) -> str:
    """
    Remove a label from a message.

    Args:
        message_id: The Gmail message ID
        label_id: The Gmail label ID to remove (use list_available_labels to find label IDs)
        account: Account identifier for multi-account (optional)

    Returns:
        Confirmation message
    """
    svc = get_service(account)
    label_name = label_id
    labels = get_labels(svc, user_id=settings.user_id)
    for label in labels:
        if label.get("id") == label_id:
            label_name = label.get("name", label_id)
            break

    result = modify_message_labels(
        svc, user_id=settings.user_id, message_id=message_id, remove_labels=[label_id], add_labels=[]
    )

    # Get message details to show what was modified (payload may be absent in minimal API response)
    subject = "No Subject"
    if result and "payload" in result:
        headers = get_headers_dict(result)
        subject = headers.get("Subject", "No Subject")

    return f"""
Label removed from message:
ID: {message_id}
Subject: {subject}
Removed Label: {label_name} ({label_id})
"""


@mcp.tool()
def get_emails(message_ids: list[str], account: Optional[str] = None) -> str:
    """
    Get the content of multiple email messages by their IDs.

    Args:
        message_ids: A list of Gmail message IDs
        account: Account identifier for multi-account (optional)

    Returns:
        The formatted content of all requested emails
    """
    if not message_ids:
        return "No message IDs provided."

    svc = get_service(account)
    retrieved_emails = []
    error_emails = []

    for msg_id in message_ids:
        try:
            message = get_message(svc, msg_id, user_id=settings.user_id)
            retrieved_emails.append((msg_id, message))
        except Exception as e:
            error_emails.append((msg_id, str(e)))

    # Build result string after fetching all emails
    result = f"Retrieved {len(retrieved_emails)} emails:\n"

    # Format all successfully retrieved emails
    for i, (msg_id, message) in enumerate(retrieved_emails, 1):
        result += f"\n--- Email {i} (ID: {msg_id}) ---\n"
        result += format_message(message)

    # Report any errors
    if error_emails:
        result += f"\n\nFailed to retrieve {len(error_emails)} emails:\n"
        for i, (msg_id, error) in enumerate(error_emails, 1):
            result += f"\n--- Email {i} (ID: {msg_id}) ---\n"
            result += f"Error: {error}\n"

    return result


@mcp.tool()
def list_drafts(max_results: int = 10, account: Optional[str] = None) -> str:
    """
    List draft emails in the mailbox.

    Args:
        max_results: Maximum number of drafts to return (default 10)
        account: Account identifier for multi-account (optional)

    Returns:
        Formatted list of draft IDs and message IDs
    """
    drafts = gmail_list_drafts(
        get_service(account), user_id=settings.user_id, max_results=max_results
    )
    result = f"Found {len(drafts)} draft(s):\n"
    for d in drafts:
        result += f"  Draft ID: {d.get('id')}  Message ID: {d.get('message', {}).get('id', 'N/A')}\n"
    return result


@mcp.tool()
def get_draft(draft_id: str, account: Optional[str] = None) -> str:
    """
    Get a draft by ID (including full message content).

    Args:
        draft_id: The Gmail draft ID
        account: Account identifier for multi-account (optional)

    Returns:
        Formatted draft content
    """
    draft = gmail_get_draft(get_service(account), draft_id, user_id=settings.user_id)
    msg = draft.get("message", {})
    result = f"Draft ID: {draft_id}\n"
    result += format_message(msg) if msg else "No message in draft."
    return result


@mcp.tool()
def send_draft(draft_id: str, account: Optional[str] = None) -> str:
    """
    Send an existing draft email.

    Args:
        draft_id: The Gmail draft ID to send
        account: Account identifier for multi-account (optional)

    Returns:
        Confirmation with sent message ID
    """
    result = gmail_send_draft(get_service(account), draft_id, user_id=settings.user_id)
    return f"Draft sent successfully. Message ID: {result.get('id')}"


@mcp.tool()
def trash_message(message_id: str, account: Optional[str] = None) -> str:
    """
    Move a message to trash.

    Args:
        message_id: The Gmail message ID to trash
        account: Account identifier for multi-account (optional)

    Returns:
        Confirmation message
    """
    gmail_trash_message(get_service(account), message_id, user_id=settings.user_id)
    return f"Message {message_id} moved to trash."


@mcp.tool()
def untrash_message(message_id: str, account: Optional[str] = None) -> str:
    """
    Remove a message from trash (restore to inbox).

    Args:
        message_id: The Gmail message ID to restore
        account: Account identifier for multi-account (optional)

    Returns:
        Confirmation message
    """
    gmail_untrash_message(get_service(account), message_id, user_id=settings.user_id)
    return f"Message {message_id} restored from trash."


@mcp.tool()
def batch_modify_labels(
    message_ids: list[str],
    add_labels: Optional[List[str]] = None,
    remove_labels: Optional[List[str]] = None,
    account: Optional[str] = None,
) -> str:
    """
    Add or remove labels on multiple messages at once.

    Args:
        message_ids: List of Gmail message IDs
        add_labels: Label IDs to add (optional)
        remove_labels: Label IDs to remove (optional)
        account: Account identifier for multi-account (optional)

    Returns:
        Confirmation message
    """
    batch_modify_messages_labels(
        get_service(account),
        message_ids=message_ids,
        add_labels=add_labels or [],
        remove_labels=remove_labels or [],
        user_id=settings.user_id,
    )
    return f"Labels updated on {len(message_ids)} message(s)."


@mcp.tool()
def create_label(name: str, account: Optional[str] = None) -> str:
    """
    Create a new Gmail label.

    Args:
        name: Label name
        account: Account identifier for multi-account (optional)

    Returns:
        Confirmation with new label ID
    """
    label = gmail_create_label(get_service(account), name, user_id=settings.user_id)
    return f"Label created: {label.get('name')} (ID: {label.get('id')})"


@mcp.tool()
def update_label(
    label_id: str,
    name: Optional[str] = None,
    label_list_visibility: Optional[str] = None,
    message_list_visibility: Optional[str] = None,
    account: Optional[str] = None,
) -> str:
    """
    Update an existing label (name or visibility).

    Args:
        label_id: The label ID to update
        name: New label name (optional)
        label_list_visibility: labelShow, labelHide, or labelShowIfUnread (optional)
        message_list_visibility: show or hide (optional)
        account: Account identifier for multi-account (optional)

    Returns:
        Confirmation message
    """
    gmail_update_label(
        get_service(account),
        label_id=label_id,
        name=name,
        label_list_visibility=label_list_visibility,
        message_list_visibility=message_list_visibility,
        user_id=settings.user_id,
    )
    return f"Label {label_id} updated."


@mcp.tool()
def delete_label(label_id: str, account: Optional[str] = None) -> str:
    """
    Delete a Gmail label.

    Args:
        label_id: The label ID to delete
        account: Account identifier for multi-account (optional)

    Returns:
        Confirmation message
    """
    gmail_delete_label(get_service(account), label_id, user_id=settings.user_id)
    return f"Label {label_id} deleted."


@mcp.tool()
def list_attachments(message_id: str, account: Optional[str] = None) -> str:
    """
    List attachments for an email message.

    Args:
        message_id: The Gmail message ID
        account: Account identifier for multi-account (optional)

    Returns:
        Formatted list of attachments (filename, attachment_id, mime_type, size)
    """
    atts = gmail_list_attachments(get_service(account), message_id, user_id=settings.user_id)
    if not atts:
        return f"Message {message_id} has no attachments."
    result = f"Message {message_id} has {len(atts)} attachment(s):\n"
    for a in atts:
        result += f"  - {a.get('filename')} (id: {a.get('attachment_id')}, size: {a.get('size', 0)} bytes)\n"
    return result


@mcp.tool()
def download_email_attachments(
    message_id: str,
    target_dir: Optional[str] = None,
    download_all_in_thread: bool = False,
    account: Optional[str] = None,
) -> str:
    """
    Download attachments from a message (or its entire thread) to a directory.

    Args:
        message_id: The Gmail message ID
        target_dir: Directory to save files (default: downloaded_attachments)
        download_all_in_thread: If True, download attachments from all messages in the thread
        account: Account identifier for multi-account (optional)

    Returns:
        Confirmation with paths to saved files
    """
    svc = get_service(account)
    directory = Path(target_dir or "downloaded_attachments")
    saved = download_attachments(
        svc,
        message_id,
        directory,
        user_id=settings.user_id,
        download_all_in_thread=download_all_in_thread,
    )
    return f"Downloaded {len(saved)} file(s) to {directory}: " + ", ".join(str(p) for p in saved)


# Prompts
@mcp.prompt()
def compose_email_prompt() -> dict:
    """Guide for composing and sending an email, or replying with optional attachments."""
    return {
        "description": "Guide for composing and sending an email, or replying to one (with optional attachments)",
        "messages": [
            {
                "role": "system",
                "content": "You're helping the user compose/send an email or reply to one. For new emails: use compose_email (draft) or send_email (send); both accept attachment_paths. For replies: use reply_to_email with message_id and body; set send=True to send immediately or False for draft; attachment_paths and html_body are optional. Collect: account (optional), recipient or message_id, subject/body, CC/BCC, attachment file paths.",
            },
            {"role": "user", "content": "I need to send an email."},
            {
                "role": "assistant",
                "content": "I'll help. Is this a new email or a reply? For new: recipient, subject, body, and optionally CC/BCC and attachment file paths. For reply: the message ID to reply to, reply body, and optionally attachment_paths. Say send=True to send now or I'll create a draft.",
            },
        ],
    }


@mcp.prompt()
def search_emails_prompt() -> dict:
    """Guide for searching emails with criteria or raw query."""
    return {
        "description": "Guide for searching emails",
        "messages": [
            {
                "role": "system",
                "content": "You're helping the user search their emails. Use search_emails for criteria (from, to, subject, dates, label, unread, has_attachment) or query_emails for a raw Gmail query. Optionally set include_conversations=True to see thread context.",
            },
            {"role": "user", "content": "I want to search my emails."},
            {
                "role": "assistant",
                "content": "I can search by: sender (from_email), recipient (to_email), subject, date range (after_date/before_date YYYY/MM/DD), label, unread, or has attachment. Or give me a raw Gmail query (e.g. from:user@example.com is:unread). Which account (optional)?",
            },
        ],
    }


@mcp.prompt()
def read_latest_emails_prompt() -> dict:
    """Guide for reading latest inbox emails, optionally with attachment download."""
    return {
        "description": "Guide for reading latest emails",
        "messages": [
            {
                "role": "system",
                "content": "You're helping the user read their recent emails. Use read_latest_emails with max_results; set download_attachments_flag=True to save attachments to a directory.",
            },
            {"role": "user", "content": "I want to check my recent emails."},
            {
                "role": "assistant",
                "content": "I'll fetch your latest inbox messages. How many would you like (default 10)? Should I download any attachments to a folder (e.g. downloaded_attachments)? Which account (optional)?",
            },
        ],
    }


@mcp.prompt()
def download_attachments_prompt() -> dict:
    """Guide for downloading email attachments (single message or full thread)."""
    return {
        "description": "Guide for downloading email attachments",
        "messages": [
            {
                "role": "system",
                "content": "You're helping the user download attachments. Use list_attachments to see what's on a message, then download_email_attachments with the message_id. Set download_all_in_thread=True to get attachments from the whole thread.",
            },
            {"role": "user", "content": "I want to download attachments from an email."},
            {
                "role": "assistant",
                "content": "I'll help you download attachments. Please provide the Message ID (from search or get_emails). Should I download from that message only or the entire conversation thread? Optional: target directory (default downloaded_attachments) and account.",
            },
        ],
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
