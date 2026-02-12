"""
Minimal CLI for Gmail operations without MCP or an AI in the loop.

Uses the same OAuth setup as the MCP server (MCP_GMAIL_CREDENTIALS_PATH,
MCP_GMAIL_TOKEN_PATH). Intended for scripts and automation (e.g. Codex
workflows) that need Gmail without starting the MCP server or using LLM tokens.

Example:
  mcp-gmail search --query "from:alice@example.com" --max 5
  mcp-gmail send --to "bob@example.com" --subject "Hi" --body "Hello"
  mcp-gmail get MESSAGE_ID
"""

import argparse
import sys

from mcp_gmail.config import settings
from mcp_gmail.gmail import (
    get_gmail_service,
    get_headers_dict,
    get_message,
    list_messages,
    parse_message_body,
    send_email,
)


def _get_sender(service):
    profile = service.users().getProfile(userId=settings.user_id).execute()
    return profile.get("emailAddress", "")


def cmd_search(args):
    service = get_gmail_service(
        credentials_path=settings.credentials_path,
        token_path=settings.token_path,
        scopes=settings.scopes,
        account=args.account,
    )
    messages, next_token = list_messages(
        service,
        user_id=settings.user_id,
        max_results=args.max,
        query=args.query or "",
        page_token=args.page_token,
    )
    for msg_info in messages:
        msg = get_message(service, msg_info["id"], user_id=settings.user_id)
        headers = get_headers_dict(msg)
        print(f"id:{msg_info['id']}\tfrom:{headers.get('From', '')}\tsubject:{headers.get('Subject', '')}")
    if next_token and args.show_next_token:
        print(f"next_page_token: {next_token}", file=sys.stderr)


def cmd_send(args):
    service = get_gmail_service(
        credentials_path=settings.credentials_path,
        token_path=settings.token_path,
        scopes=settings.scopes,
        account=args.account,
    )
    sender = _get_sender(service)
    body = args.body
    if args.body_file:
        with open(args.body_file, "r") as f:
            body = f.read()
    send_email(
        service,
        sender=sender,
        to=args.to,
        subject=args.subject,
        body=body,
        user_id=settings.user_id,
        cc=args.cc,
        bcc=args.bcc,
    )
    print("sent", file=sys.stderr)


def cmd_get(args):
    service = get_gmail_service(
        credentials_path=settings.credentials_path,
        token_path=settings.token_path,
        scopes=settings.scopes,
        account=args.account,
    )
    msg = get_message(service, args.message_id, user_id=settings.user_id)
    headers = get_headers_dict(msg)
    body = parse_message_body(msg)
    print("From:", headers.get("From", ""))
    print("To:", headers.get("To", ""))
    print("Subject:", headers.get("Subject", ""))
    print("Date:", headers.get("Date", ""))
    print()
    print(body)


def main():
    parser = argparse.ArgumentParser(
        description="Gmail CLI (no MCP, no AI). Uses MCP_GMAIL_CREDENTIALS_PATH and MCP_GMAIL_TOKEN_PATH."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_search = sub.add_parser("search", help="List/search messages (Gmail query syntax)")
    p_search.add_argument("--query", "-q", default="", help="Gmail search query")
    p_search.add_argument("--max", "-n", type=int, default=10, help="Max results")
    p_search.add_argument("--page-token", help="Page token from previous response")
    p_search.add_argument("--show-next-token", action="store_true", help="Print next_page_token to stderr")
    p_search.add_argument("--account", "-a", help="Account key from token file (default if omitted)")
    p_search.set_defaults(func=cmd_search)

    p_send = sub.add_parser("send", help="Send an email")
    p_send.add_argument("--to", "-t", required=True, help="Recipient")
    p_send.add_argument("--subject", "-s", required=True, help="Subject")
    p_send.add_argument("--body", "-b", default="", help="Body text")
    p_send.add_argument("--body-file", help="Read body from file (overrides --body)")
    p_send.add_argument("--cc", help="CC recipients")
    p_send.add_argument("--bcc", help="BCC recipients")
    p_send.add_argument("--account", "-a", help="Account key from token file (default account if omitted)")
    p_send.set_defaults(func=cmd_send)

    p_get = sub.add_parser("get", help="Get one message by ID")
    p_get.add_argument("message_id", help="Gmail message ID")
    p_get.add_argument("--account", "-a", help="Account key from token file (default account if omitted)")
    p_get.set_defaults(func=cmd_get)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
