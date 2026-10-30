from __future__ import annotations

from pathlib import Path

import pytest

from agentgate import tools
from agentgate.gateway import Session
from agentgate.policy import load_policy_set
from agentgate.store import Store

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def policies():
    return load_policy_set(ROOT / "data" / "principals.json", ROOT / "data" / "policies.json")


@pytest.fixture()
def state(tmp_path):
    store = Store(tmp_path / "agentgate.sqlite")
    assert store.load_documents_from_dir(ROOT / "data" / "documents") == 4
    return store


@pytest.fixture()
def session(state, policies):
    def make(actor: str = "analyst", origin: str = "human") -> Session:
        return Session(state, policies, actor, origin)
    return make


@pytest.fixture(autouse=True)
def _clear_executions():
    tools.reset_executions()
    yield
    tools.reset_executions()
