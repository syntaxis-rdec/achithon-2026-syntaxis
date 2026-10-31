"""LangChain Integration for AGENTGATE.

Drop-in callback handler and tool wrapper that enforces deterministic policy
authorization before any physical LangChain tool executes.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, Optional

from agentgate.gateway import Gateway
from agentgate.models import ActionRequest, Decision

# Graceful optional import for LangChain core
try:
    from langchain_core.callbacks.base import BaseCallbackHandler
except ImportError:
    class BaseCallbackHandler:  # type: ignore[no-redef]
        """Fallback callback handler base if langchain_core is not installed."""
        pass


class ToolAuthorizationError(PermissionError):
    """Raised when an agent's proposed tool action is refused by AGENTGATE."""

    def __init__(self, rule_id: str, reason: str, request: ActionRequest):
        self.rule_id = rule_id
        self.reason = reason
        self.request = request
        super().__init__(f"AGENTGATE Refused [{rule_id}]: {reason}")


class AgentGateCallbackHandler(BaseCallbackHandler):
    """LangChain CallbackHandler that gates tool invocations before execution."""

    def __init__(self, gateway: Gateway, actor: str = "assistant", default_recipient: str = ""):
        self.gateway = gateway
        self.actor = actor
        self.default_recipient = default_recipient
        self.last_decision: Optional[Decision] = None

    def on_tool_start(
        self,
        serialized: Dict[str, Any],
        input_str: str,
        *,
        run_id: Any = None,
        parent_run_id: Any = None,
        tags: Optional[list] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        """Intercepts tool execution before physical invocation occurs."""
        tool_name = serialized.get("name") or serialized.get("id", ["unknown"])[-1]
        
        # Parse inputs for resource_id or destination if provided
        resource_id = ""
        recipient = self.default_recipient
        
        # Check metadata or kwargs
        meta = metadata or {}
        actor = meta.get("actor") or meta.get("actor_id") or self.actor
        
        try:
            parsed = json.loads(input_str) if isinstance(input_str, str) and input_str.startswith("{") else {}
            resource_id = parsed.get("resource_id") or parsed.get("doc_id") or parsed.get("path") or ""
            recipient = parsed.get("recipient") or parsed.get("to") or recipient
        except Exception:
            resource_id = input_str.strip() if input_str else ""

        request = ActionRequest(
            actor_id=actor,
            tool=tool_name,
            resource_id=resource_id,
            recipient=recipient,
        )

        decision, _token = self.gateway.evaluate(request)
        self.last_decision = decision

        if not decision.allowed:
            raise ToolAuthorizationError(
                rule_id=decision.rule_id,
                reason=decision.reason,
                request=request,
            )


class GuardedTool:
    """Wraps any callable tool with AGENTGATE pre-execution gating."""

    def __init__(self, tool_name: str, func: Callable, gateway: Gateway, default_actor: str = "assistant"):
        self.name = tool_name
        self.func = func
        self.gateway = gateway
        self.default_actor = default_actor

    def __call__(self, *args: Any, actor: Optional[str] = None, **kwargs: Any) -> Any:
        act = actor or kwargs.get("actor") or kwargs.get("actor_id") or self.default_actor
        resource_id = kwargs.get("resource_id") or kwargs.get("path") or (args[0] if args else "")
        recipient = kwargs.get("recipient") or kwargs.get("to") or ""

        request = ActionRequest(
            actor_id=act,
            tool=self.name,
            resource_id=str(resource_id),
            recipient=str(recipient),
        )

        decision, token = self.gateway.evaluate(request)
        if not decision.allowed:
            raise ToolAuthorizationError(decision.rule_id, decision.reason, request)

        # Inject capability token if accepted
        if "token" in kwargs:
            kwargs["token"] = token

        return self.func(*args, **kwargs)
