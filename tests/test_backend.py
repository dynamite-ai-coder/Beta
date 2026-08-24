from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.config import is_url_allowed
from backend.models.schemas import (
    AISelectors,
    DOMElement,
    TaskRequest,
    TaskState,
)
from backend.security.auth import (
    create_session_token,
    redact_secret,
    sanitize_filename,
    validate_session_token,
)


class TestURLAllowlist:
    def test_block_localhost(self):
        assert not is_url_allowed("http://localhost/login")

    def test_block_127_0_0_1(self):
        assert not is_url_allowed("http://127.0.0.1/admin")

    def test_block_private_network(self):
        assert not is_url_allowed("http://192.168.1.1/login")
        assert not is_url_allowed("http://10.0.0.1/dashboard")
        assert not is_url_allowed("http://172.16.0.1/auth")

    def test_block_metadata_endpoint(self):
        assert not is_url_allowed("http://169.254.169.254/latest/meta-data")
        assert not is_url_allowed("http://metadata.google.internal/computeMetadata/v1/")

    def test_block_link_local(self):
        assert not is_url_allowed("http://169.254.1.1/")

    def test_allow_http(self):
        with patch("backend.config.settings") as mock_settings:
            mock_settings.allowed_domains_list = ["example.com"]
            assert is_url_allowed("http://example.com/login")

    def test_allow_https(self):
        with patch("backend.config.settings") as mock_settings:
            mock_settings.allowed_domains_list = ["example.com"]
            assert is_url_allowed("https://example.com/dashboard")

    def test_block_non_http(self):
        assert not is_url_allowed("ftp://example.com")
        assert not is_url_allowed("file:///etc/passwd")
        assert not is_url_allowed("javascript:alert(1)")

    def test_domain_allowlist(self):
        with patch("backend.config.settings") as mock_settings:
            mock_settings.allowed_domains_list = ["trusted.com"]
            assert is_url_allowed("https://trusted.com/login")
            assert not is_url_allowed("https://untrusted.com/login")


class TestTaskRequestValidation:
    def test_valid_request(self):
        req = TaskRequest(
            target_url="https://example.com/login",
            username="testuser",
            password="testpass",
        )
        assert req.target_url == "https://example.com/login"

    def test_invalid_url_no_protocol(self):
        with pytest.raises(Exception):
            TaskRequest(
                target_url="example.com/login",
                username="testuser",
                password="testpass",
            )

    def test_empty_username_rejected(self):
        with pytest.raises(Exception):
            TaskRequest(
                target_url="https://example.com",
                username="",
                password="pass",
            )


class TestAISelectors:
    def test_valid_selectors(self):
        sel = AISelectors(
            username_selector="#username",
            password_selector="#password",
            submit_selector="button[type=submit]",
            confidence=0.95,
            reason="Found standard login form elements",
        )
        assert sel.confidence == 0.95

    def test_confidence_bounds(self):
        with pytest.raises(Exception):
            AISelectors(
                username_selector="#u",
                password_selector="#p",
                submit_selector="#s",
                confidence=1.5,
                reason="test",
            )


class TestDOMElement:
    def test_element_creation(self):
        el = DOMElement(
            tag="input",
            id="username",
            name="user",
            type="text",
            placeholder="Enter username",
        )
        assert el.tag == "input"
        assert el.id == "username"


class TestSecurityAuth:
    def test_sanitize_filename(self):
        assert sanitize_filename("hello") == "hello"
        result = sanitize_filename("../../../etc/passwd")
        assert "/" not in result
        result2 = sanitize_filename("user@name.com")
        assert "@" not in result2
        assert sanitize_filename("a" * 200) == "a" * 100
        result3 = sanitize_filename("file with spaces.txt")
        assert " " not in result3

    def test_session_token(self):
        token = create_session_token()
        assert len(token) > 20
        assert validate_session_token(token) is True

    def test_invalid_token(self):
        assert validate_session_token("invalid-token-123") is False

    def test_redact_secret(self):
        result = redact_secret("password is secret123", "secret123")
        assert "secret123" not in result
        assert "[REDACTED]" in result

    def test_redact_empty_secret(self):
        result = redact_secret("password is visible", "")
        assert result == "password is visible"


class TestTaskState:
    def test_task_states_exist(self):
        assert TaskState.QUEUED == "QUEUED"
        assert TaskState.SUCCESS == "SUCCESS"
        assert TaskState.FAILURE == "FAILURE"
        assert TaskState.WAITING_FOR_MANUAL_ACTION == "WAITING_FOR_MANUAL_ACTION"


class TestAIResponseParsing:
    def test_parse_valid_json(self):
        from backend.ai.provider import AIProvider

        provider = AIProvider()
        json_str = '{"username_selector": "#user", "password_selector": "#pass", "submit_selector": "button", "confidence": 0.9, "reason": "test"}'
        result = provider._parse_json_response(json_str)
        assert result is not None
        assert result.username_selector == "#user"

    def test_parse_json_with_code_block(self):
        from backend.ai.provider import AIProvider

        provider = AIProvider()
        json_str = '```json\n{"username_selector": "#user", "password_selector": "#pass", "submit_selector": "button", "confidence": 0.9, "reason": "test"}\n```'
        result = provider._parse_json_response(json_str)
        assert result is not None

    def test_parse_invalid_json(self):
        from backend.ai.provider import AIProvider

        provider = AIProvider()
        result = provider._parse_json_response("not json at all")
        assert result is None


class TestCAPCHADetection:
    def test_captcha_keywords(self):
        from backend.browser.driver import detect_captcha

        mock_driver = MagicMock()
        mock_driver.page_source = "Please complete the CAPTCHA to continue"
        mock_driver.find_elements.return_value = []
        assert detect_captcha(mock_driver) is True

    def test_cloudflare_detection(self):
        from backend.browser.driver import detect_captcha

        mock_driver = MagicMock()
        mock_driver.page_source = "Checking if the site connection is secure. Cloudflare security check."
        mock_driver.find_elements.return_value = []
        assert detect_captcha(mock_driver) is True

    def test_no_captcha(self):
        from backend.browser.driver import detect_captcha

        mock_driver = MagicMock()
        mock_driver.page_source = "<html><body>Welcome to the dashboard</body></html>"
        mock_driver.find_elements.return_value = []
        assert detect_captcha(mock_driver) is False
