import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared_protocol import (
    MsgType, ProtocolMsg, Complexity,
    pack_preprocess, pack_classify, pack_extract, pack_simplify,
    unpack_preprocess_reply, unpack_classify_reply,
    unpack_extract_reply, unpack_simplify_reply,
    pack_ping, pack_pong, pack_status,
    pack_agent_input, pack_agent_output, pack_agent_error,
    decode_any, msg_type_name, token_savings,
)


class TestProtocolMsg:
    def test_encode_decode(self):
        msg = ProtocolMsg(type=MsgType.PREPROCESS, src="test", dst="localai", payload={"m": "hello"})
        encoded = msg.encode()
        decoded = ProtocolMsg.decode(encoded)
        assert decoded.type == MsgType.PREPROCESS
        assert decoded.payload["m"] == "hello"

    def test_decode_invalid(self):
        decoded = ProtocolMsg.decode("invalid_base85!!!")
        assert decoded.type == 0
        assert "raw" in decoded.payload


class TestPreprocess:
    def test_pack_preprocess(self):
        encoded = pack_preprocess("test message", "file context", "pl")
        assert isinstance(encoded, str)
        msg = decode_any(encoded)
        assert msg.type == MsgType.PREPROCESS
        assert msg.payload["m"] == "test message"
        assert msg.payload["fc"] == "file context"
        assert msg.payload["l"] == "pl"

    def test_unpack_preprocess_reply(self):
        msg = ProtocolMsg(type=MsgType.PREPROCESS_REPLY, payload={"p": "improved", "o": "original", "ok": 1, "ms": 50})
        result = unpack_preprocess_reply(msg.encode())
        assert result["processed"] == "improved"
        assert result["original"] == "original"
        assert result["success"] is True
        assert result["latency_ms"] == 50


class TestClassify:
    def test_pack_classify(self):
        encoded = pack_classify("what is python?")
        msg = decode_any(encoded)
        assert msg.type == MsgType.CLASSIFY
        assert msg.payload["m"] == "what is python?"

    def test_unpack_classify_reply(self):
        msg = ProtocolMsg(type=MsgType.CLASSIFY_REPLY, payload={"cx": "simple", "ag": ["solver"], "sk": ["planner"], "c": 0.9})
        result = unpack_classify_reply(msg.encode())
        assert result["complexity"] == "simple"
        assert result["agents"] == ["solver"]
        assert result["skip"] == ["planner"]
        assert result["confidence"] == 0.9


class TestExtract:
    def test_pack_extract(self):
        encoded = pack_extract("some text", ["key1", "key2"])
        msg = decode_any(encoded)
        assert msg.type == MsgType.EXTRACT
        assert msg.payload["t"] == "some text"
        assert msg.payload["k"] == ["key1", "key2"]

    def test_unpack_extract_reply(self):
        msg = ProtocolMsg(type=MsgType.EXTRACT_REPLY, payload={"e": {"key": "val"}, "pt": "plain", "ok": 1})
        result = unpack_extract_reply(msg.encode())
        assert result["extracted"] == {"key": "val"}
        assert result["plain_text"] == "plain"
        assert result["success"] is True


class TestSimplify:
    def test_pack_simplify(self):
        encoded = pack_simplify("long text here", 50)
        msg = decode_any(encoded)
        assert msg.type == MsgType.SIMPLIFY
        assert msg.payload["t"] == "long text here"
        assert msg.payload["w"] == 50

    def test_unpack_simplify_reply(self):
        msg = ProtocolMsg(type=MsgType.SIMPLIFY_REPLY, payload={"s": "short", "ow": 100, "sw": 20})
        result = unpack_simplify_reply(msg.encode())
        assert result["simplified"] == "short"
        assert result["original_words"] == 100
        assert result["simplified_words"] == 20


class TestSystemMessages:
    def test_ping_pong(self):
        ping = pack_ping()
        pong = pack_pong()
        assert decode_any(ping).type == MsgType.PING
        assert decode_any(pong).type == MsgType.PONG

    def test_status(self):
        encoded = pack_status({"status": "ok", "uptime": 100})
        msg = decode_any(encoded)
        assert msg.type == MsgType.STATUS
        assert msg.payload["status"] == "ok"


class TestAgentMessages:
    def test_agent_input(self):
        encoded = pack_agent_input("solver", "solve this", "context here")
        msg = decode_any(encoded)
        assert msg.type == MsgType.AGENT_INPUT
        assert msg.payload["a"] == "solver"
        assert msg.payload["t"] == "solve this"

    def test_agent_output(self):
        encoded = pack_agent_output("solver", "solution here", 0.9, 150)
        msg = decode_any(encoded)
        assert msg.type == MsgType.AGENT_OUTPUT
        assert msg.payload["r"] == "solution here"
        assert msg.payload["c"] == 0.9
        assert msg.payload["tk"] == 150

    def test_agent_error(self):
        encoded = pack_agent_error("critic", "failed", "TIMEOUT")
        msg = decode_any(encoded)
        assert msg.type == MsgType.AGENT_ERROR
        assert msg.payload["e"] == "failed"
        assert msg.payload["code"] == "TIMEOUT"


class TestUtility:
    def test_msg_type_name(self):
        msg = ProtocolMsg(type=MsgType.PREPROCESS)
        assert msg_type_name(msg) == "PREPROCESS"

        unknown = ProtocolMsg(type=0xFF)
        assert "UNKNOWN" in msg_type_name(unknown)

    def test_token_savings(self):
        savings = token_savings("short", "this is a much longer json equivalent text")
        assert savings["saved"] > 0
        assert savings["savings_pct"] > 0
