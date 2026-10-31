"""Model Context Protocol (MCP) Interceptor for AGENTGATE.

Provides pre-flight authorization gating for tools exposed via MCP (Model
Context Protocol) JSON-RPC standard.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from agentgate.gateway import Gateway
from agentgate.models import ActionRequest, Decision


class MCPToolInterceptor:
    """Gates Model Context Protocol `tools/call` requests before execution."""

    def __init__(self, gateway: Gateway, default_actor: str = "assistant"):
        self.gateway = gateway
        self.default_actor = default_actor

    def intercept(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        actor: Optional[str] = None,
    ) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        """Intercepts an MCP tools/call request.

        Returns:
            (allowed: bool, rejection_reason: Optional[str], gated_arguments: dict)
        """
        act = actor or arguments.get("actor") or arguments.get("actor_id") or self.default_actor
        resource_id = str(
            arguments.get("resource_id")
            or arguments.get("path")
            or arguments.get("file")
            or ""
        )
        recipient = str(
            arguments.get("recipient")
            or arguments.get("to")
            or arguments.get("email")
            or ""
        )

        request = ActionRequest(
            actor_id=act,
            tool=tool_name,
            resource_id=resource_id,
            recipient=recipient,
        )

        decision, token = self.gateway.evaluate(request)
        if not decision.allowed:
            return False, f"[{decision.rule_id}] {decision.reason}", arguments

        # Attach capability token to arguments
        authorized_args = dict(arguments)
        authorized_args["_agentgate_token"] = token
        return True, None, authorized_args
