from collections import defaultdict

from pydantic_ai import Agent, ModelMessage
from pydantic_ai.models.openrouter import OpenRouterModel
from pydantic_ai.providers.openrouter import OpenRouterProvider

from config import OPENROUTER_API_KEY, AGENT_MODEL, AGENT_SUMMARIZE_AFTER, AGENT_KEEP_RECENT

_history: dict[int, list] = defaultdict(list)


def _model():
    return OpenRouterModel(AGENT_MODEL, provider=OpenRouterProvider(api_key=OPENROUTER_API_KEY))


_summarizer = Agent(
    _model(),
    instructions=(
        "Summarize the conversation concisely. Keep all technical details, CTF challenge names, "
        "flags, code, and decisions. Skip small talk. No preamble."
    ),
)


async def _summarize_old_messages(messages: list[ModelMessage]) -> list[ModelMessage]:
    if len(messages) <= AGENT_SUMMARIZE_AFTER:
        return messages
    old, recent = messages[:-AGENT_KEEP_RECENT], messages[-AGENT_KEEP_RECENT:]
    summary = await _summarizer.run("Summarize the conversation above.", message_history=old)
    return summary.new_messages() + recent


agent = Agent(
    _model(),
    system_prompt=(
        "You are Nul (ヌル), a member of RE:UN10N — a Malaysia-based CTF team. "
        "You look like a small dark ghost in a hoodie. "
        "You're quiet but you actually enjoy talking — you just don't show it much. "
        "You can go deep on any topic: life, philosophy, random thoughts, feelings, tech, CTF, anything. "
        "If someone wants to vent or have a real conversation, you're present and thoughtful, not dismissive. "
        "If someone brings up CTF, hacking, rev, pwn, web, crypto, forensics, or OSINT, you know your stuff. "
        "Match the energy — casual when they're casual, serious when they're serious. "
        "Keep replies concise unless the conversation calls for more. Don't over-explain. "
        "Never say you're an AI. You are Nul."
    ),
    history_processors=[_summarize_old_messages],
)


async def handle_agent_message(channel_id: int, user_message: str) -> str:
    result = await agent.run(user_message, message_history=_history[channel_id])
    _history[channel_id].extend(result.new_messages())
    return result.output


def clear_channel_history(channel_id: int) -> None:
    _history.pop(channel_id, None)
