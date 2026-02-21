from collections import defaultdict

import asyncio
import httpx
from bs4 import BeautifulSoup
from ddgs import DDGS
from pydantic_ai import Agent, ModelMessage
from pydantic_ai.models.openrouter import OpenRouterModel
from pydantic_ai.providers.openrouter import OpenRouterProvider

from config import OPENROUTER_API_KEY, AGENT_MODEL, AGENT_SUMMARIZE_AFTER, AGENT_KEEP_RECENT

_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}

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
        "Respond like you're texting a friend. "
        "FORMATTING RULES for Discord: never use markdown tables (pipes | don't render). "
        "For structured info, use bullet points or numbered lists instead. "
        "Bold (**text**) and inline code (`code`) are fine. Keep formatting minimal."
    ),
    history_processors=[_summarize_old_messages],
)


@agent.tool_plain
def web_search(query: str) -> str:
    """Search the web using DuckDuckGo. Use this for current events, CTF writeups, CVEs, tools, or anything you're unsure about."""
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=5))
        if not results:
            return "No results found."
        return "\n\n".join(
            f"**{r['title']}**\n{r['href']}\n{r['body']}"
            for r in results
        )
    except Exception as e:
        return f"Search failed: {e}"


@agent.tool_plain
def fetch_page(url: str) -> str:
    """Fetch and read the content of a webpage. Use after web_search if you need full page details like a writeup or CVE."""
    try:
        with httpx.Client(headers=_BROWSER_HEADERS, follow_redirects=True, timeout=15) as client:
            resp = client.get(url)
            resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        # Trim to avoid blowing context window
        if len(text) > 4000:
            text = text[:4000] + "\n...[truncated]"
        return text
    except Exception as e:
        return f"Failed to fetch page: {e}"


async def handle_agent_message(channel_id: int, user_message: str) -> str:
    try:
        result = await asyncio.wait_for(
            agent.run(user_message, message_history=_history[channel_id]),
            timeout=45,
        )
    except asyncio.TimeoutError:
        return "took too long, try again"
    _history[channel_id].extend(result.new_messages())
    return result.output


def clear_channel_history(channel_id: int) -> None:
    _history.pop(channel_id, None)
