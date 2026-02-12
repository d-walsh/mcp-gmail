# MCP Gmail Server

A Model Context Protocol (MCP) server that provides Gmail access for LLMs, powered by the [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk).

## Features

- **Resources:** Messages, threads, and inbox (default and per-account)
- **Compose & send:** Drafts and send with optional file attachments
- **Search:** Criteria-based and raw Gmail query; optional conversation/thread context
- **Labels:** List, add/remove on messages, batch modify, create/update/delete labels
- **Drafts:** List, get, and send drafts
- **Trash:** Move messages to trash and restore
- **Attachments:** List attachments, download to a directory (single message or full thread)
- **Multi-account:** Optional account parameter on tools; use separate token files (e.g. `token_work.json`)
- **Prompts:** Guided prompts for compose, search, read latest, and download attachments
- OAuth 2.0 authentication with Google's Gmail API

## Prerequisites

- Python 3.10+
- Gmail account with API access
- [uv](https://github.com/astral-sh/uv) for Python package management (recommended)

## Setup

### 1. Install dependencies

Install project dependencies (uv automatically creates and manages a virtual environment)
```bash
uv sync
```

### 2. Configure Gmail OAuth credentials

There's unfortunately a lot of steps required to use the Gmail API. I've attempted to capture all of the required steps (as of March 28, 2025) but things may change.

#### Google Cloud Setup

1. **Create a Google Cloud Project**
    - Go to [Google Cloud Console](https://console.cloud.google.com/)
    - Click on the project dropdown at the top of the page
    - Click "New Project"
    - Enter a project name (e.g., "MCP Gmail Integration")
    - Click "Create"
    - Wait for the project to be created and select it from the dropdown

2. **Enable the Gmail API**
    - In your Google Cloud project, go to the navigation menu (≡)
    - Select "APIs & Services" > "Library"
    - Search for "Gmail API"
    - Click on the Gmail API card
    - Click "Enable"

3. **Configure OAuth Consent Screen**
    - Go to "APIs & Services" > "OAuth consent screen"
    - You will likely see something like "Google Auth Platform not configured yet"
        - Click on "Get started"
    - Fill in the required application information:
        - App name: "MCP Gmail Integration"
        - User support email: Your email address
    - Fill in the required audience information:
        - Choose "External" user type (unless you have a Google Workspace organization)
    - Fill in the required contact information:
        - Your email address
    - Click "Save and Continue"
   - Click "Create"

4. **Create OAuth Credentials**
   - Go to "APIs & Services" > "Credentials"
   - Click "Create Credentials" > "OAuth client ID"
   - Choose "Desktop app" as the application type
   - Enter a name (e.g., "MCP Gmail Desktop Client")
   - Click "Create"
   - Click "Download JSON" for the credentials you just created
   - Save the file as `credentials.json` in your project root directory

5. **Add scopes**
    - Go to "APIs & Services" > "OAuth consent screen"
    - Go to the "Data Access" tab
    - Click "Add or remove scopes"
    - Search for the Gmail API
    - Select the scope for `.../auth/gmail.modify` which grants permission to "Read, compose, and send emails from your Gmail account"
    - Click update
    - Click save

Verify that you've set up your OAuth configuration correctly by running a simple test script.

```bash
uv run python scripts/test_gmail_setup.py
```

You should be able to see usage metrics at https://console.cloud.google.com/apis/api/gmail.googleapis.com/metrics

### 3. Run the server

Development mode:
```bash
uv run mcp dev mcp_gmail/server.py
```

This will spin up an MCP Inspector application that you can use to interact with the MCP server.

Or install for use with Claude Desktop:
```bash
uv run mcp install \
    --with-editable .
    --name gmail \
    --env-var MCP_GMAIL_CREDENTIALS_PATH=$(pwd)/credentials.json \
    --env-var MCP_GMAIL_TOKEN_PATH=$(pwd)/token.json \
    mcp_gmail/server.py
```

> [!NOTE]
> If you encounter an error like `Error: spawn uv ENOENT` when spinning up Claude Desktop and initializing the MCP server, you may need to update your `claude_desktop_config.json` to provide the **absolute** path to `uv`. Go to Claude Desktop -> Settings -> Developer -> Edit Config.
>
> ```json
> {
>   "mcpServers": {
>     "gmail": {
>       "command": "~/.local/bin/uv",
>     }
>   }
> }
> ```

## Development

### Linting and Testing

Run linting and formatting:
```bash
# Format code
uv run ruff format .

# Lint code with auto-fixes where possible
uv run ruff check --fix .

# Run tests
uv run pytest tests/
```

### Pre-commit Hooks

This project uses pre-commit hooks to ensure code quality. The hooks automatically run before each commit to verify code formatting and linting standards.

Install the pre-commit hooks:
```bash
pre-commit install
```

Run pre-commit manually on all files:
```bash
pre-commit run --all-files
```

## Usage

### Using as a Python library (no AI / no MCP)

You can use the Gmail logic directly from Python (e.g. scripts, Codex workflows, cron jobs) without running the MCP server or any LLM. Same OAuth setup (`credentials.json`, `token.json`).

```python
from mcp_gmail.gmail import (
    get_gmail_service,
    send_email,
    search_messages,
    get_message,
    get_headers_dict,
    parse_message_body,
)

# Auth uses MCP_GMAIL_CREDENTIALS_PATH / MCP_GMAIL_TOKEN_PATH if set, else defaults
service = get_gmail_service(
    credentials_path="credentials.json",
    token_path="token.json",
)

# Send an email (no MCP, no tokens)
profile = service.users().getProfile(userId="me").execute()
sender = profile.get("emailAddress")
send_email(service, sender=sender, to="someone@example.com", subject="Hi", body="Hello")

# Search and read messages
messages, next_token = search_messages(service, from_email="alice@example.com", max_results=5)
for msg_info in messages:
    msg = get_message(service, msg_info["id"])
    headers = get_headers_dict(msg)
    body = parse_message_body(msg)
    print(headers.get("Subject"), body[:200])
```

All operations in `mcp_gmail.gmail` (e.g. `create_draft`, `send_reply`, `query_emails` via `list_messages`, `modify_message_labels`, `get_labels`) are available this way. Use this for token-heavy or fully automated workflows without an AI in the middle.

**CLI (same credentials, no MCP):** After `uv sync`, you can run Gmail from the shell so scripted or Codex workflows don’t need an AI in the loop:

```bash
# Search (Gmail query syntax)
uv run mcp-gmail search --query "from:alice@example.com" --max 5 --show-next-token

# Send
uv run mcp-gmail send --to "bob@example.com" --subject "Hi" --body "Hello"

# Get one message
uv run mcp-gmail get MESSAGE_ID
```

Set `MCP_GMAIL_CREDENTIALS_PATH` and `MCP_GMAIL_TOKEN_PATH` (or rely on defaults) so the CLI uses the same OAuth setup as the MCP server.

### Using via MCP (with Claude Desktop or other MCP clients)

Once running, you can connect to the MCP server using any MCP client or via Claude Desktop.

### Available Resources

- `gmail://messages/{message_id}` - Access email messages
- `gmail://threads/{thread_id}` - Access email threads
- `gmail://inbox` - Latest inbox messages (default account)
- `gmail://inbox/{account}` - Latest inbox messages for a specific account

### Available Tools

Tools accept an optional **`account`** parameter for multi-account use (token file is derived as `token_{account}.json` by default).

**Compose & send**
- `compose_email` - Create a new email draft (optional `attachment_paths`)
- `send_email` - Send an email (optional `attachment_paths`)
- `reply_to_email` - Reply to a message (draft or send; optional `html_body`, `attachment_paths`)

**Search & read**
- `search_emails` - Search with filters (from, to, subject, dates, label, unread, etc.); optional `include_conversations`
- `query_emails` - Raw Gmail query syntax
- `read_latest_emails` - Latest inbox messages; optional attachment download to a directory
- `get_emails` - Get multiple messages by ID

**Drafts**
- `list_drafts` - List draft IDs
- `get_draft` - Get draft content by ID
- `send_draft` - Send an existing draft

**Labels**
- `list_available_labels` - List all labels and IDs
- `add_label_to_message` - Add a label to a message
- `remove_label_from_message` - Remove a label from a message
- `batch_modify_labels` - Add/remove labels on multiple messages
- `create_label` - Create a new label
- `update_label` - Update label name or visibility
- `delete_label` - Delete a label

**State & attachments**
- `mark_message_read` - Remove UNREAD label
- `trash_message` - Move message to trash
- `untrash_message` - Restore message from trash
- `list_attachments` - List attachments for a message (filename, id, size)
- `download_email_attachments` - Download attachments to a directory (optionally whole thread)

**Prompts** (guided flows)
- `compose_email_prompt` - Guide for composing/sending an email
- `search_emails_prompt` - Guide for searching
- `read_latest_emails_prompt` - Guide for reading recent emails
- `download_attachments_prompt` - Guide for downloading attachments

### Pagination

When listing or searching emails, the Gmail API returns at most `max_results` per request and may have more results. The MCP supports pagination so an agent can page through all matches:

- **`search_emails`** and **`query_emails`** accept an optional **`page_token`** (omit it for the first page).
- The tool response includes a **`next_page_token`** line when more results are available. To get the next page, call the same tool again with `page_token` set to that value (and the same other arguments).
- If there is no `next_page_token` in the response, there are no more pages.

Example flow for an agent:
1. Call `search_emails(...)` or `query_emails(...)` with no `page_token`.
2. If the response contains `next_page_token: <token>`, call again with `page_token=<token>` to get the next page.
3. Repeat until the response has no `next_page_token`.

You can also raise `max_results` (or set `MCP_GMAIL_MAX_RESULTS`) to get more results per page (Gmail API allows up to 500).

### Multi-account

Use a different Gmail account by passing the **`account`** parameter on tools (and optionally on resources via `gmail://inbox/{account}`).

**Two modes:**

1. **Single token file (default)**  
   All accounts use the same token file (e.g. `token.json`). The file holds one object per account, e.g. `{"default": {...}, "work": {...}}` or `{"david@gmail.com": {...}, "work@company.com": {...}}`. The `account` parameter must match the key in the file. Run the OAuth flow once per account; tokens are stored under that key in the same file.

2. **Multiple token files**  
   Set `MCP_GMAIL_MULTI_ACCOUNT_SINGLE_FILE=false`. For `account="work"` the server uses a separate file, e.g. `token_work.json`. Run the OAuth flow once per account; each account gets its own file.

**If you already have both accounts in one token file:**  
Ensure the file is valid JSON with one top-level object whose keys are account identifiers and whose values are Google OAuth token objects (each with `refresh_token`, `token`, etc.). No env change needed (single-file is the default). Pass the same key as the `account` parameter on tools (omit `account` or use the key for your primary account as default).

## Environment Variables

You can configure the server using environment variables:

- `MCP_GMAIL_CREDENTIALS_PATH`: Path to the OAuth credentials JSON file (default: "credentials.json")
- `MCP_GMAIL_TOKEN_PATH`: Path to store the OAuth token (default: "token.json"). With multiple files, tokens are `{path_stem}_{account}{ext}` (e.g. `token_work.json`). With single-file mode, this one file holds all accounts.
- `MCP_GMAIL_MAX_RESULTS`: Default maximum results for search/inbox queries (default: 10)
- `MCP_GMAIL_MULTI_ACCOUNT_SINGLE_FILE`: If true (default), all accounts use the same token file (keys: `default`, `work`, or email). If false, each account uses a separate file with suffix (e.g. `token_work.json`).

## License

MIT
