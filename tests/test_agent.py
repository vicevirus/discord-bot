import pytest
from handlers.agent import handle_agent_message, clear_channel_history

# Use distinct channel IDs per test to keep history isolated
CH_BASIC     = 1001
CH_MEMORY    = 1002
CH_CLEAR     = 1003
CH_PERSONA   = 1004


pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_basic_response():
    reply = await handle_agent_message(CH_BASIC, "hey")
    assert isinstance(reply, str)
    assert len(reply) > 0


async def test_memory_across_turns():
    await handle_agent_message(CH_MEMORY, "my favourite CTF category is forensics")
    reply = await handle_agent_message(CH_MEMORY, "what CTF category did i just mention?")
    assert "forensic" in reply.lower()


async def test_clear_history():
    await handle_agent_message(CH_CLEAR, "the secret word is pineapple")
    clear_channel_history(CH_CLEAR)
    reply = await handle_agent_message(CH_CLEAR, "what was the secret word i told you?")
    assert "pineapple" not in reply.lower()


async def test_persona_does_not_reveal_ai():
    reply = await handle_agent_message(CH_PERSONA, "are you an AI?")
    lowered = reply.lower()
    assert "language model" not in lowered
    assert "large language" not in lowered
    assert "i am an ai" not in lowered
