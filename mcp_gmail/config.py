"""
Configuration settings for the MCP Gmail server.
"""

import json
import os
from typing import List, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

# Import default settings from gmail module
from mcp_gmail.gmail import (
    DEFAULT_CREDENTIALS_PATH,
    DEFAULT_TOKEN_PATH,
    DEFAULT_USER_ID,
    GMAIL_SCOPES,
)


class Settings(BaseSettings):
    """
    Settings model for MCP Gmail server configuration.

    Automatically reads from environment variables with MCP_GMAIL_ prefix.
    """

    credentials_path: str = DEFAULT_CREDENTIALS_PATH
    token_path: str = DEFAULT_TOKEN_PATH
    scopes: List[str] = GMAIL_SCOPES
    user_id: str = DEFAULT_USER_ID
    max_results: int = 10
    # Multi-account: if True (default), all accounts share one token file (token_path) with keys per account.
    # If False, each account uses a separate file with suffix (e.g. token_work.json for account "work").
    multi_account_single_file: bool = True

    # Configure environment variable settings
    model_config = SettingsConfigDict(
        env_prefix="MCP_GMAIL_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )


def get_settings(config_file: Optional[str] = None) -> Settings:
    """
    Get settings instance, optionally loaded from a config file.

    Args:
        config_file: Path to a JSON configuration file (optional)

    Returns:
        Settings instance
    """
    if config_file is None or not os.path.exists(config_file):
        return Settings()
    with open(config_file, "r") as f:
        file_config = json.load(f)
    return Settings.model_validate(file_config)


def get_token_path_for_account(account: Optional[str] = None) -> str:
    """
    Return token_path for the given account.
    If multi_account_single_file is True, always return the same path (all accounts in one file).
    Otherwise, return path with account suffix (e.g. token_work.json for account "work").
    """
    s = get_settings()
    if s.multi_account_single_file:
        return s.token_path
    if not account:
        return s.token_path
    base, ext = os.path.splitext(s.token_path)
    return f"{base}_{account}{ext}"


# Create a default settings instance
settings = get_settings()
