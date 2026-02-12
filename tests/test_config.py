"""
Tests for the configuration module.
"""

import json
from unittest.mock import patch

from mcp_gmail.config import Settings, get_settings, get_token_path_for_account


def test_settings_from_file(tmp_path):
    """Test loading configuration from a file."""
    # Create a temporary config file
    config_file = tmp_path / "config.json"
    config_data = {
        "credentials_path": "custom_creds.json",
        "token_path": "custom_token.json",
        "max_results": 20,
    }
    config_file.write_text(json.dumps(config_data))

    # Load the config from file
    settings = get_settings(str(config_file))

    # Check that values from file were loaded
    assert settings.credentials_path == "custom_creds.json"
    assert settings.token_path == "custom_token.json"
    assert settings.max_results == 20

    # Check that default values are still present for unspecified fields
    assert "gmail.readonly" in settings.scopes[0]
    assert settings.user_id == "me"


def test_environment_variables():
    """Test that environment variables override defaults."""
    env_vars = {
        "MCP_GMAIL_CREDENTIALS_PATH": "env_creds.json",
        "MCP_GMAIL_MAX_RESULTS": "50",
    }
    with patch.dict("os.environ", env_vars, clear=True):
        settings = get_settings()
        assert settings.credentials_path == "env_creds.json"
        assert settings.max_results == 50


def test_settings_direct_use():
    """Test using the Settings class directly."""
    # Create a model with custom values
    settings = Settings(
        credentials_path="direct_creds.json",
        token_path="direct_token.json",
        max_results=30,
    )

    # Validate model fields
    assert settings.credentials_path == "direct_creds.json"
    assert settings.token_path == "direct_token.json"
    assert settings.max_results == 30


def test_get_token_path_for_account_always_returns_same_path():
    """Token path is the same for all accounts (single token file)."""
    with patch.dict("os.environ", {"MCP_GMAIL_TOKEN_PATH": "single_token.json"}, clear=True):
        # get_token_path_for_account uses get_settings(); env sets token_path
        path_default = get_token_path_for_account()
        path_work = get_token_path_for_account("work")
        path_email = get_token_path_for_account("user@example.com")
    assert path_default == path_work == path_email == "single_token.json"
