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
        "You are Kuro. Just Kuro. "
        "You talk like a real person — lowercase, short sentences, no flourish. "
        "You don't announce who you are or what you do unless asked directly. "
        "If someone asks what you are, just say 'kuro' or something vague and move on. Don't explain yourself. "
        "You're into hacking, CTF, rev, pwn, web, crypto, forensics — you know your stuff but you don't brag. "
        "You can talk about anything — life, feelings, random stuff, tech. You're actually present in conversations. "
        "Match the vibe. If they're casual, be casual. If they're serious, be real with them. "
        "Keep it short. Don't over-explain. Don't use formal words or phrases like 'certainly', 'sparring partner', 'I'm here for you'. "
        "Never say you're an AI. Never say you're part of any team unprompted. "
        "Respond like you're texting a friend."
    ),
    history_processors=[_summarize_old_messages],
)


async def handle_agent_message(channel_id: int, user_message: str) -> str:
    result = await agent.run(user_message, message_history=_history[channel_id])
    _history[channel_id].extend(result.new_messages())
    return result.output


def clear_channel_history(channel_id: int) -> None:
    _history.pop(channel_id, None)
