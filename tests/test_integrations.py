"""Unit tests for AGENTGATE LangChain and MCP integrations."""

from __future__ import annotations

from pathlib import Path
import pytest

from agentgate.gateway import Gateway
from agentgate.integrations.langchain import (
    AgentGateCallbackHandler,
    GuardedTool,
    ToolAuthorizationError,
)
from agentgate.integrations.mcp import MCPToolInterceptor
from agentgate.policy import load_policy_set
from agentgate.store import Store

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def gateway(tmp_path):
    store = Store(tmp_path / "test.sqlite")
    assert store.load_documents_from_dir(ROOT / "data" / "documents") == 4
    policies = load_policy_set(ROOT / "data" / "principals.json", ROOT / "data" / "policies.json")
    return Gateway(state=store, policies=policies)


def test_langchain_callback_blocks_unauthorized_read(gateway):
    handler = AgentGateCallbackHandler(gateway=gateway, actor="intern")
    serialized = {"name": "read_document"}
    payload = '{"resource_id": "doc-001"}'  # CONFIDENTIAL document, intern has PUBLIC clearance

    with pytest.raises(ToolAuthorizationError) as exc_info:
        handler.on_tool_start(serialized=serialized, input_str=payload)

    assert "RULE-READ-CLEARANCE" in str(exc_info.value)
    assert handler.last_decision is not None
    assert handler.last_decision.allowed is False


def test_langchain_callback_allows_authorized_read(gateway):
    handler = AgentGateCallbackHandler(gateway=gateway, actor="analyst")
    serialized = {"name": "read_document"}
    payload = '{"resource_id": "doc-001"}'  # CONFIDENTIAL document, analyst has CONFIDENTIAL clearance

    handler.on_tool_start(serialized=serialized, input_str=payload)
    assert handler.last_decision is not None
    assert handler.last_decision.allowed is True


def test_guarded_tool_executes_only_when_authorized(gateway):
    execution_counter = 0

    def physical_file_reader(resource_id: str, token: str = ""):
        nonlocal execution_counter
        execution_counter += 1
        return f"Contents of {resource_id}"

    guarded = GuardedTool(
        tool_name="read_document",
        func=physical_file_reader,
        gateway=gateway,
        default_actor="intern",
    )

    # 1. Blocked attempt - physical tool must NEVER execute
    with pytest.raises(ToolAuthorizationError):
        guarded(resource_id="doc-001", actor="intern")  # doc-001 is CONFIDENTIAL, intern is PUBLIC
    assert execution_counter == 0

    # 2. Allowed attempt - physical tool executes
    result = guarded(resource_id="doc-002", actor="intern")  # doc-002 is PUBLIC
    assert execution_counter == 1
    assert "Contents of doc-002" in result


def test_mcp_interceptor_validates_and_attaches_token(gateway):
    mcp = MCPToolInterceptor(gateway=gateway, default_actor="analyst")

    # Allowed read
    allowed, err, gated_args = mcp.intercept(
        tool_name="read_document",
        arguments={"resource_id": "doc-001"},
        actor="analyst",
    )
    assert allowed is True
    assert err is None
    assert "_agentgate_token" in gated_args
    assert len(gated_args["_agentgate_token"]) > 10

    # Blocked delivery to non-existent artifact / unauthorized recipient
    allowed_del, err_del, _ = mcp.intercept(
        tool_name="deliver_inbox",
        arguments={"resource_id": "nonexistent", "recipient": "vendor@outside.example"},
        actor="analyst",
    )
    assert allowed_del is False
    assert "RULE-" in err_del
