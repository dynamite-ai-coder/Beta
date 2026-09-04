from __future__ import annotations

import os
import sys
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestOrchestrator:
    @pytest.mark.anyio
    async def test_orchestrator_process_request(self):
        from backend.ai.models import VirtualAIRequest
        from backend.ai.orchestrator import AIOrchestrator

        orchestrator = AIOrchestrator()
        request = VirtualAIRequest(
            model="beta-virtual-ai",
            messages=[{"role": "user", "content": "What is 2+2?"}],
        )

        with patch.object(orchestrator, '_run_agent') as mock_agent:
            mock_agent.return_value = MagicMock(
                success=True,
                raw_response="The answer is 4",
                parsed={"solution": "4"},
                confidence=0.95,
                tokens_used=50,
            )

            response = await orchestrator.process(request)
            assert response.id.startswith("beta-")
            assert response.model == "beta-virtual-ai"
            assert len(response.choices) == 1

    def test_orchestrator_has_five_agents(self):
        from backend.ai.orchestrator import AIOrchestrator
        from backend.ai.agent_roles import AgentRole

        orchestrator = AIOrchestrator()
        assert len(orchestrator.agents) == 5
        for role in AgentRole:
            assert role in orchestrator.agents


class TestGroqAgentClient:
    def test_agent_config_loading(self):
        from backend.config import settings

        for i in range(1, 6):
            config = settings.get_agent_config(i)
            assert "api_key" in config
            assert "model" in config
            assert "base_url" in config
            assert config["base_url"] == "https://api.groq.com/openai/v1"

    def test_agent_roles_have_system_prompts(self):
        from backend.ai.agent_roles import AgentRole, AGENT_SYSTEM_PROMPTS

        for role in AgentRole:
            assert role in AGENT_SYSTEM_PROMPTS
            assert len(AGENT_SYSTEM_PROMPTS[role]) > 50


class TestRateLimiting:
    def test_rate_limit_configured(self):
        from backend.config import settings

        assert settings.max_ai_workflows >= 1
        assert settings.max_deliberation_rounds >= 1
        assert settings.rate_limit_per_minute >= 1


class TestVirtualAIRequest:
    def test_valid_request(self):
        from backend.ai.models import VirtualAIRequest

        req = VirtualAIRequest(
            model="beta-virtual-ai",
            messages=[{"role": "user", "content": "Hello"}],
        )
        assert req.model == "beta-virtual-ai"
        assert len(req.messages) == 1

    def test_default_values(self):
        from backend.ai.models import VirtualAIRequest

        req = VirtualAIRequest(
            model="beta-virtual-ai",
            messages=[{"role": "user", "content": "Test"}],
        )
        assert req.temperature == 0.7
        assert req.max_tokens == 4096
        assert req.stream is False


class TestAIContext:
    def test_context_creation(self):
        from backend.ai.models import AIContext

        ctx = AIContext(
            task_id="test-123",
            original_request="Solve this problem",
        )
        assert ctx.task_id == "test-123"
        assert ctx.state == "initialized"
        assert ctx.confidence == 0.5

    def test_compact_summary(self):
        from backend.ai.models import AIContext

        ctx = AIContext(
            task_id="test-123",
            original_request="Solve this problem",
            plan=["step1", "step2"],
            evidence=["fact1"],
        )
        summary = ctx.get_compact_summary()
        assert "Solve this problem" in summary
        assert "step1" in summary


class TestClientUI:
    def test_local_ui_config(self):
        from client.config import ClientConfig

        config = ClientConfig()
        assert config.local_ui_host == "127.0.0.1"
        assert config.local_ui_port == 23400

    def test_chat_client_history(self):
        from client.config import ClientConfig
        from client.chat import ChatClient

        config = ClientConfig()
        chat = ChatClient(config)
        assert len(chat.history) == 0

        chat.add_user_message("Hello")
        assert len(chat.history) == 1
        assert chat.history[0]["role"] == "user"

        chat.add_assistant_message("Hi there")
        assert len(chat.history) == 2
        assert chat.history[1]["role"] == "assistant"

    def test_chat_client_clear(self):
        from client.config import ClientConfig
        from client.chat import ChatClient

        config = ClientConfig()
        chat = ChatClient(config)
        chat.add_user_message("Hello")
        chat.clear_history()
        assert len(chat.history) == 0

    def test_file_manager_validation(self):
        from client.config import ClientConfig
        from client.files.manager import FileManager

        config = ClientConfig()
        fm = FileManager(config)

        valid, msg = fm.validate_file("test.txt", 1000)
        assert valid is True

        valid, msg = fm.validate_file("test.exe", 1000)
        assert valid is False

        valid, msg = fm.validate_file("test.txt", 100 * 1024 * 1024)
        assert valid is False

    def test_file_info(self):
        from client.config import ClientConfig
        from client.files.manager import FileManager

        config = ClientConfig()
        fm = FileManager(config)

        info = fm.get_file_info("document.pdf", 5000)
        assert info["name"] == "document.pdf"
        assert info["extension"] == ".pdf"
        assert info["type"] == "pdf"


class TestLocalAI:
    def test_local_ai_disabled_by_default(self):
        from client.local_ai import get_status
        status = get_status()
        assert status["enabled"] is False
        assert status["loaded"] is False

    def test_simple_request_bypass(self):
        from client.local_ai import preprocess_prompt
        orig, ctx = preprocess_prompt("Hello world")
        assert orig == "Hello world"
        assert ctx == ""

    def test_short_question_bypass(self):
        from client.local_ai import preprocess_prompt
        orig, ctx = preprocess_prompt("What time is it?")
        assert orig == "What time is it?"
        assert ctx == ""

    def test_complex_request_detected(self):
        from client.local_ai import _is_complex_request
        assert _is_complex_request("Analyze this code and explain how it works")
        assert _is_complex_request("Compare Python and JavaScript performance")
        assert _is_complex_request("What are the differences? What should I choose?")
        assert _is_complex_request("A" * 400)

    def test_simple_request_not_complex(self):
        from client.local_ai import _is_complex_request
        assert not _is_complex_request("Hello")
        assert not _is_complex_request("What time is it?")
        assert not _is_complex_request("hi")

    def test_file_context_makes_complex(self):
        from client.local_ai import _is_complex_request
        assert _is_complex_request("Analyze", "x" * 600)

    def test_context_extraction(self):
        from client.local_ai import _extract_context_summary
        ctx = _extract_context_summary("test message", "line1\nline2\nline3")
        assert "File context" in ctx or "Key points" in ctx

    def test_is_available_false_without_model(self):
        from client.local_ai import is_local_ai_available
        assert is_local_ai_available() is False

    def test_config_local_ai_settings(self):
        from client.config import ClientConfig
        config = ClientConfig()
        assert config.local_ai_enabled is False
        assert config.local_ai_model == ""
        assert config.local_ai_context == 2048
        assert config.local_ai_max_tokens == 256
        assert config.local_ai_threads == 2
