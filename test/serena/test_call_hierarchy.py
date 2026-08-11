"""Tests for the call hierarchy tools.

These tools are specific to this fork (they do not exist upstream), so they have no
upstream test coverage to inherit. They reach into solidlsp internals
(``lang_server.server.send.*``) that upstream is free to refactor, so this file is the
tripwire for that: it exercises the real LSP round-trip rather than mocking it.

The fixture chain used throughout is, in ``test/resources/repos/python/test_repo``:

    main()  ->  UserManager.register_user()  ->  UserService.create_user()
"""

import json
from collections.abc import Iterator

import pytest

from serena.agent import SerenaAgent
from serena.tools import GetIncomingCallsTool, GetOutgoingCallsTool
from solidlsp.ls_config import LanguageServerId
from test.conftest import agent_for_project_context, get_pytest_markers

LS_ID = LanguageServerId.PYTHON

pytestmark = get_pytest_markers(LS_ID)

SERVICES_PATH = "test_repo/services.py"
MANAGEMENT_PATH = "examples/user_management.py"


@pytest.fixture(scope="module")
def agent() -> Iterator[SerenaAgent]:
    # Module-scoped: starting a language server per test would dominate runtime.
    with agent_for_project_context(LS_ID) as a:
        yield a


def _names(nodes: list[dict]) -> set[str]:
    return {n["name"] for n in nodes}


class TestGetIncomingCalls:
    def test_direct_callers(self, agent: SerenaAgent) -> None:
        result = json.loads(
            agent.get_tool(GetIncomingCallsTool).apply(name_path="UserService/create_user", relative_path=SERVICES_PATH, depth=1)
        )

        assert result["direction"] == "incoming"
        assert result["target"]["name"] == "create_user"
        assert result["target"]["file"] == SERVICES_PATH
        assert "register_user" in _names(result["callers"])
        assert result["total_callers"] == len(result["callers"])

        caller = next(c for c in result["callers"] if c["name"] == "register_user")
        assert caller["file"] == MANAGEMENT_PATH
        assert caller["depth"] == 1
        # depth=1 must not recurse
        assert "children" not in caller

    def test_depth_2_recurses_to_callers_of_callers(self, agent: SerenaAgent) -> None:
        result = json.loads(
            agent.get_tool(GetIncomingCallsTool).apply(name_path="UserService/create_user", relative_path=SERVICES_PATH, depth=2)
        )

        caller = next(c for c in result["callers"] if c["name"] == "register_user")
        assert "children" in caller, "depth=2 should expand callers-of-callers"
        assert "main" in _names(caller["children"])
        assert all(child["depth"] == 2 for child in caller["children"])
        # total_callers counts the whole tree, not just the top level
        assert result["total_callers"] > len(result["callers"])


class TestGetOutgoingCalls:
    def test_direct_callees(self, agent: SerenaAgent) -> None:
        result = json.loads(
            agent.get_tool(GetOutgoingCallsTool).apply(name_path="UserManager/register_user", relative_path=MANAGEMENT_PATH, depth=1)
        )

        assert result["direction"] == "outgoing"
        assert result["target"]["name"] == "register_user"
        assert "create_user" in _names(result["callees"])
        assert result["total_callees"] == len(result["callees"])


def test_unknown_symbol_raises(agent: SerenaAgent) -> None:
    with pytest.raises(ValueError):
        agent.get_tool(GetIncomingCallsTool).apply(name_path="NoSuchClass/no_such_method", relative_path=SERVICES_PATH)
