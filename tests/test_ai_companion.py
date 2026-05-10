from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from server.ai_companion import ask, scope_to_sources, search


def test_scope_to_sources_chat():
    assert scope_to_sources("chat") == ["team_chat"]


def test_scope_to_sources_meetings():
    assert scope_to_sources("meetings") == ["meeting"]


def test_scope_to_sources_docs():
    assert scope_to_sources("docs") == ["zoom_doc"]


def test_scope_to_sources_all():
    assert sorted(scope_to_sources("all")) == sorted(
        ["team_chat", "meeting", "zoom_doc"]
    )


def test_scope_to_sources_default():
    assert sorted(scope_to_sources(None)) == sorted(
        ["team_chat", "meeting", "zoom_doc"]
    )


def test_scope_to_sources_unknown_falls_back_to_all():
    assert sorted(scope_to_sources("garbage")) == sorted(
        ["team_chat", "meeting", "zoom_doc"]
    )


@pytest.mark.asyncio
async def test_search_returns_results():
    oauth = MagicMock()
    oauth.make_authenticated_request = AsyncMock(
        return_value=httpx.Response(200, json={"results": [{"id": "r1"}]})
    )
    out = await search(oauth, query="q", scope="all")
    assert out["results"][0]["id"] == "r1"


@pytest.mark.asyncio
async def test_search_rejects_empty_query():
    oauth = MagicMock()
    with pytest.raises(ValueError):
        await search(oauth, query="")


@pytest.mark.asyncio
async def test_search_403_surfaces_friendly_error():
    oauth = MagicMock()
    oauth.make_authenticated_request = AsyncMock(
        return_value=httpx.Response(403, json={"error": "forbidden"})
    )
    with pytest.raises(RuntimeError, match="AI Companion is not enabled"):
        await search(oauth, query="q")


@pytest.mark.asyncio
async def test_ask_returns_answer_and_citations():
    oauth = MagicMock()
    oauth.make_authenticated_request = AsyncMock(
        return_value=httpx.Response(
            200,
            json={
                "answer": "It's blue.",
                "citations": [{"source_type": "team_chat", "source_id": "M1"}],
            },
        )
    )
    out = await ask(oauth, question="What colour?", scope="chat")
    assert out["answer"] == "It's blue."
    assert out["citations"][0]["source_id"] == "M1"


@pytest.mark.asyncio
async def test_ask_rejects_empty_question():
    oauth = MagicMock()
    with pytest.raises(ValueError):
        await ask(oauth, question="   ")
