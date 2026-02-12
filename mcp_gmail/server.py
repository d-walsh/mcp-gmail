"""
Gmail MCP Server Implementation

This module provides a Model Context Protocol server for interacting with Gmail.
It exposes Gmail messages as resources and provides tools for composing and sending emails.
"""

import re
from datetime import datetime
from typing import Optional

from mcp.server.fastmcp import FastMCP

from mcp_gmail.config import settings
from mcp_gmail.gmail import (
    create_draft,
    create_reply_draft,
    get_gmail_service,
    get_headers_dict,
    get_labels,
    get_message,
    get_thread,
    list_messages,
    modify_message_labels,
    parse_message_body,
    search_messages,
    send_reply,
)
from mcp_gmail.gmail import send_email as gmail_send_email

# Lazy-initialize Gmail service so MCP handshake completes before any auth/network calls
_service = None


def get_service():
    global _service
    if _service is None:
        _service = get_gmail_service(
            credentials_path=settings.credentials_path,
            token_path=settings.token_path,
            scopes=settings.scopes,
        )
    return _service


mcp = FastMCP(
    "Gmail MCP Server",
    instructions="""Access and interact with Gmail. You can get messages, threads, search emails, and send or compose new messages.

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


# Tools
@mcp.tool()
def compose_email(
    to: str, subject: str, body: str, cc: Optional[str] = None, bcc: Optional[str] = None
) -> str:
    """
    Compose a new email draft.

    Args:
        to: Recipient email address
        subject: Email subject
        body: Email body content
        cc: Carbon copy recipients (optional)
        bcc: Blind carbon copy recipients (optional)

    Returns:
        The ID of the created draft and its content
    """
    sender = get_service().users().getProfile(userId=settings.user_id).execute().get("emailAddress")
    draft = create_draft(
        get_service(), sender=sender, to=to, subject=subject, body=body, user_id=settings.user_id, cc=cc, bcc=bcc
    )

    draft_id = draft.get("id")
    return f"""
Email draft created with ID: {draft_id}
To: {to}
Subject: {subject}
CC: {cc or ""}
BCC: {bcc or ""}
Body: {body[:EMAIL_PREVIEW_LENGTH]}{"..." if len(body) > EMAIL_PREVIEW_LENGTH else ""}
"""


@mcp.tool()
def send_email(
    to: str, subject: str, body: str, cc: Optional[str] = None, bcc: Optional[str] = None
) -> str:
    """
    Compose and send an email.

    Args:
        to: Recipient email address
        subject: Email subject
        body: Email body content
        cc: Carbon copy recipients (optional)
        bcc: Blind carbon copy recipients (optional)

    Returns:
        Content of the sent email
    """
    sender = get_service().users().getProfile(userId=settings.user_id).execute().get("emailAddress")
    message = gmail_send_email(
        get_service(), sender=sender, to=to, subject=subject, body=body, user_id=settings.user_id, cc=cc, bcc=bcc
    )

    message_id = message.get("id")
    return f"""
Email sent successfully with ID: {message_id}
To: {to}
Subject: {subject}
CC: {cc or ""}
BCC: {bcc or ""}
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
    send: bool = False,
) -> str:
    """
    Reply to an existing email, keeping the reply in the same thread.

    By default creates a draft with reply-all (includes all original recipients).
    Set reply_all=False to reply only to the sender.
    Set send=True to send immediately.
    Provide html_body for rich formatting (tables, bold, etc.).

    Args:
        message_id: The Gmail message ID to reply to
        body: Reply body content (plain text)
        reply_all: If True, include all original To/CC recipients (default: True)
        to: Override recipient (default: reply to sender)
        cc: Additional CC recipients to merge with reply-all recipients (optional)
        bcc: Blind carbon copy recipients (optional)
        html_body: HTML version of the body for rich formatting (optional)
        send: If True, send immediately; if False, create draft (default: False)

    Returns:
        Confirmation with draft/message ID and details
    """
    sender = get_service().users().getProfile(userId=settings.user_id).execute().get("emailAddress")

    # Get original message details for display
    original = get_message(get_service(), message_id, user_id=settings.user_id)
    original_headers = get_headers_dict(original)
    original_subject = original_headers.get("Subject", "No Subject")
    reply_to = to or original_headers.get("Reply-To", original_headers.get("From", ""))

    if send:
        result = send_reply(
            get_service(),
            message_id=message_id,
            sender=sender,
            body=body,
            user_id=settings.user_id,
            reply_all=reply_all,
            to=to,
            cc=cc,
            bcc=bcc,
            html_body=html_body,
        )
        result_id = result.get("id")
        return f"""
Reply sent successfully with ID: {result_id}
In reply to: {original_subject}
To: {reply_to}
CC: {cc or "(none)"}
Reply-All: {reply_all}
Body: {body[:EMAIL_PREVIEW_LENGTH]}{"..." if len(body) > EMAIL_PREVIEW_LENGTH else ""}
"""
    else:
        result = create_reply_draft(
            get_service(),
            message_id=message_id,
            sender=sender,
            body=body,
            user_id=settings.user_id,
            reply_all=reply_all,
            to=to,
            cc=cc,
            bcc=bcc,
            html_body=html_body,
        )
        draft_id = result.get("id")
        return f"""
Reply draft created with ID: {draft_id}
In reply to: {original_subject}
To: {reply_to}
CC: {cc or "(none)"}
Reply-All: {reply_all}
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

    Returns:
        Formatted list of matching emails. Includes next_page_token when more results are available.
    """
    # Validate date formats
    if after_date and not validate_date_format(after_date):
        return f"Error: after_date '{after_date}' is not in the required format YYYY/MM/DD"

    if before_date and not validate_date_format(before_date):
        return f"Error: before_date '{before_date}' is not in the required format YYYY/MM/DD"

    # Use search_messages to find matching emails
    messages, next_page_token = search_messages(
        get_service(),
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
        message = get_message(get_service(), msg_id, user_id=settings.user_id)
        headers = get_headers_dict(message)

        from_header = headers.get("From", "Unknown")
        subject = headers.get("Subject", "No Subject")
        date = headers.get("Date", "Unknown Date")

        result += f"\nMessage ID: {msg_id}\n"
        result += f"From: {from_header}\n"
        result += f"Subject: {subject}\n"
        result += f"Date: {date}\n"

    return result


@mcp.tool()
def query_emails(
    query: str, max_results: int = 10, page_token: Optional[str] = None
) -> str:
    """
    Search for emails using a raw Gmail query string.

    Args:
        query: Gmail search query (same syntax as Gmail search box)
        max_results: Maximum number of results to return
        page_token: Token for the next page (omit for first page; use next_page_token from previous response)

    Returns:
        Formatted list of matching emails. Includes next_page_token when more results are available.
    """
    messages, next_page_token = list_messages(
        get_service(),
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
        message = get_message(get_service(), msg_id, user_id=settings.user_id)
        headers = get_headers_dict(message)

        from_header = headers.get("From", "Unknown")
        subject = headers.get("Subject", "No Subject")
        date = headers.get("Date", "Unknown Date")

        result += f"\nMessage ID: {msg_id}\n"
        result += f"From: {from_header}\n"
        result += f"Subject: {subject}\n"
        result += f"Date: {date}\n"

    return result


@mcp.tool()
def list_available_labels() -> str:
    """
    Get all available Gmail labels for the user.

    Returns:
        Formatted list of labels with their IDs
    """
    labels = get_labels(get_service(), user_id=settings.user_id)

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
def mark_message_read(message_id: str) -> str:
    """
    Mark a message as read by removing the UNREAD label.

    Args:
        message_id: The Gmail message ID to mark as read

    Returns:
        Confirmation message
    """
    # Remove the UNREAD label
    result = modify_message_labels(
        get_service(), user_id=settings.user_id, message_id=message_id, remove_labels=["UNREAD"], add_labels=[]
    )

    # Get message details to show what was modified
    headers = get_headers_dict(result)
    subject = headers.get("Subject", "No Subject")

    return f"""
Message marked as read:
ID: {message_id}
Subject: {subject}
"""


@mcp.tool()
def add_label_to_message(message_id: str, label_id: str) -> str:
    """
    Add a label to a message.

    Args:
        message_id: The Gmail message ID
        label_id: The Gmail label ID to add (use list_available_labels to find label IDs)

    Returns:
        Confirmation message
    """
    # Add the specified label
    result = modify_message_labels(
        get_service(), user_id=settings.user_id, message_id=message_id, remove_labels=[], add_labels=[label_id]
    )

    # Get message details to show what was modified (payload may be absent in minimal API response)
    subject = "No Subject"
    if result and "payload" in result:
        headers = get_headers_dict(result)
        subject = headers.get("Subject", "No Subject")

    # Get the label name for the confirmation message
    label_name = label_id
    labels = get_labels(get_service(), user_id=settings.user_id)
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
def remove_label_from_message(message_id: str, label_id: str) -> str:
    """
    Remove a label from a message.

    Args:
        message_id: The Gmail message ID
        label_id: The Gmail label ID to remove (use list_available_labels to find label IDs)

    Returns:
        Confirmation message
    """
    # Get the label name before we remove it
    label_name = label_id
    labels = get_labels(get_service(), user_id=settings.user_id)
    for label in labels:
        if label.get("id") == label_id:
            label_name = label.get("name", label_id)
            break

    # Remove the specified label
    result = modify_message_labels(
        get_service(), user_id=settings.user_id, message_id=message_id, remove_labels=[label_id], add_labels=[]
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
def get_emails(message_ids: list[str]) -> str:
    """
    Get the content of multiple email messages by their IDs.

    Args:
        message_ids: A list of Gmail message IDs

    Returns:
        The formatted content of all requested emails
    """
    if not message_ids:
        return "No message IDs provided."

    # Fetch all emails first
    retrieved_emails = []
    error_emails = []

    for msg_id in message_ids:
        try:
            message = get_message(get_service(), msg_id, user_id=settings.user_id)
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


if __name__ == "__main__":
    mcp.run(transport="stdio")
