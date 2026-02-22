from collections import defaultdict
from contextvars import ContextVar
from datetime import datetime, timezone, timedelta
import json
import re

import asyncio
import anthropic
import httpx
from bs4 import BeautifulSoup
from ddgs import DDGS
from pydantic_ai import Agent, ModelMessage
from pydantic_ai.models.anthropic import AnthropicModel, AnthropicModelSettings
from pydantic_ai.providers.anthropic import AnthropicProvider

# Holds the active stream's queue so async tools can push status events into it.
# ContextVar ensures concurrent streams don't interfere.
_status_q: ContextVar[asyncio.Queue | None] = ContextVar('_kuro_status_q', default=None)

from config import BONSAI_API_KEY, AGENT_MODEL, AGENT_SUMMARIZE_AFTER, AGENT_KEEP_RECENT

BONSAI_MAGIC = "You are Claude Code, Anthropic's official CLI for Claude."


class _BonsaiTransport(httpx.AsyncHTTPTransport):
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.method not in ("POST", b"POST") or b"/messages" not in request.url.raw_path:
            return await super().handle_async_request(request)
        body = json.loads(request.content)
        sys = body.get("system", "")
        extra = ([{"type": "text", "text": sys}] if isinstance(sys, str) and sys
                 else sys if isinstance(sys, list) else [])
        body["system"] = [{"type": "text", "text": BONSAI_MAGIC}] + extra
        body.pop("tool_choice", None)
        body["stream"] = True
        raw = json.dumps(body).encode()
        return await super().handle_async_request(httpx.Request(
            method=request.method, url=request.url,
            headers=[(k, v) for k, v in request.headers.raw if k.lower() != b"content-length"]
                    + [(b"content-length", str(len(raw)).encode())],
            content=raw,
        ))


def _make_provider():
    return AnthropicProvider(anthropic_client=anthropic.AsyncAnthropic(
        auth_token=BONSAI_API_KEY,
        base_url="https://go.trybons.ai",
        http_client=httpx.AsyncClient(transport=_BonsaiTransport()),
    ))


def _model():
    return AnthropicModel(
        AGENT_MODEL,
        provider=_make_provider(),
    )


_MODEL_SETTINGS = AnthropicModelSettings(
    extra_headers={"User-Agent": "claude-cli/2.1.50 (external, cli)"}
)

_BROWSER_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Priority": "u=0, i",
    "Sec-CH-UA": '"Not(A:Brand";v="8", "Chromium";v="144", "Brave";v="144"',
    "Sec-CH-UA-Mobile": "?1",
    "Sec-CH-UA-Platform": '"Android"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Sec-GPC": "1",
    "Upgrade-Insecure-Requests": "1",
    "User-Agent": "Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Mobile Safari/537.36",
}

_history: dict[int, list] = defaultdict(list)


_summarizer = Agent(
    _model(),
    instructions=(
        "Summarize the conversation concisely. Keep all technical details, CTF challenge names, "
        "flags, code, and decisions. Skip small talk. No preamble."
    ),
    retries=2,
    model_settings=_MODEL_SETTINGS,
)


async def _summarize_old_messages(messages: list[ModelMessage]) -> list[ModelMessage]:
    if len(messages) <= AGENT_SUMMARIZE_AFTER:
        return messages
    old, recent = messages[:-AGENT_KEEP_RECENT], messages[-AGENT_KEEP_RECENT:]
    try:
        async with asyncio.timeout(20):
            async with _summarizer.run_stream("Summarize the conversation above.", message_history=old) as result:
                await result.get_output()
                new_msgs = result.new_messages()
            return new_msgs + recent
    except Exception:
        return recent


agent = Agent(
    _model(),
    retries=2,
    model_settings=_MODEL_SETTINGS,
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
        "If a question needs current or external info you don't know for sure, use web_search — don't guess. "
        "You also have access to CTFtime: use get_upcoming_ctfs to fetch upcoming public CTF competitions from ctftime.org. "
        "This is READ-ONLY. Never attempt to create, modify, or delete CTF channels or challenges. "
        "TOOL DISCIPLINE — critical: when you call any tool, output ZERO text in that same turn. "
        "No 'let me check', no 'one sec', nothing. Just the tool call, silently. "
        "Write your response ONLY after all tools are done and you have the results. "
        "FORMATTING RULES for Discord: never use markdown tables (pipes | don't render). "
        "For structured info, use bullet points or numbered lists instead. "
        "Bold (**text**) and inline code (`code`) are fine. Keep formatting minimal."
    ),
    history_processors=[_summarize_old_messages],
)


@agent.system_prompt
def _current_date() -> str:
    my_time = datetime.now(timezone(timedelta(hours=8)))
    return f"Current date and time (Malaysia, UTC+8): {my_time.strftime('%B %d, %Y %H:%M')}."


@agent.tool_plain
async def web_search(query: str) -> str:
    """Search the web using DuckDuckGo. Use this for current events, CTF writeups, CVEs, tools, or anything you're unsure about."""
    q = _status_q.get()
    if q is not None:
        q.put_nowait(('status', f'searching: *{query}*'))
        await asyncio.sleep(0)  # yield so consumer can render the status
    try:
        results = await asyncio.to_thread(
            lambda: list(DDGS(timeout=10).text(query, max_results=5))
        )
        if not results:
            return "No results found."
        return "\n\n".join(
            f"**{r['title']}**\n{r['href']}\n{r['body']}"
            for r in results
        )
    except Exception as e:
        return f"Search failed: {e}"


_GH_TREE = re.compile(
    r"https?://github\.com/([^/]+)/([^/]+)/tree/([^/]+)/(.*)"
)
_GH_BLOB = re.compile(
    r"https?://github\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.*)"
)
_GH_REPO = re.compile(
    r"https?://github\.com/([^/]+)/([^/\?#]+)/?(?:[^/]*)$"
)


async def _fetch_github(url: str, start: int) -> str | None:
    """Handle github.com URLs via API/raw instead of scraping HTML.
    Returns content string or None if not a recognised GitHub URL."""
    api_headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    async with httpx.AsyncClient(headers=api_headers, follow_redirects=True, timeout=15) as client:
        # Tree (directory listing)
        m = _GH_TREE.match(url)
        if m:
            owner, repo, ref, path = m.groups()
            path = path.rstrip('/')
            api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}?ref={ref}"
            resp = await client.get(api_url)
            resp.raise_for_status()
            items = resp.json()
            if isinstance(items, list):
                lines = [f"Directory: {owner}/{repo}/{path} @ {ref[:8]}\n"]
                for item in items:
                    icon = "📁" if item["type"] == "dir" else "📄"
                    lines.append(f"{icon} {item['name']} ({item.get('size', 0)} bytes)" if item["type"] == "file"
                                 else f"{icon} {item['name']}/")
                text = "\n".join(lines)
            else:
                # Single file returned (path was a file, not dir)
                raw_url = items.get("download_url") or items.get("html_url", url)
                resp2 = await client.get(raw_url)
                text = resp2.text
            chunk = text[start:start + 8000]
            if not chunk:
                return "No more content at this offset."
            if start + 8000 < len(text):
                chunk += f"\n...[truncated — call fetch_page with start={start + 8000} for more]"
            return chunk

        # Blob (single file view) → fetch raw content
        m = _GH_BLOB.match(url)
        if m:
            owner, repo, ref, path = m.groups()
            raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}"
            resp = await client.get(raw_url)
            resp.raise_for_status()
            text = resp.text
            chunk = text[start:start + 8000]
            if not chunk:
                return "No more content at this offset."
            if start + 8000 < len(text):
                chunk += f"\n...[truncated — call fetch_page with start={start + 8000} for more]"
            return chunk

        # Bare repo URL → repo info
        m = _GH_REPO.match(url)
        if m:
            owner, repo = m.group(1), m.group(2)
            resp = await client.get(f"https://api.github.com/repos/{owner}/{repo}")
            resp.raise_for_status()
            d = resp.json()
            text = (
                f"Repo: {d.get('full_name')}\n"
                f"Description: {d.get('description')}\n"
                f"Stars: {d.get('stargazers_count')}  Forks: {d.get('forks_count')}\n"
                f"Language: {d.get('language')}\n"
                f"Topics: {', '.join(d.get('topics', []))}\n"
                f"Default branch: {d.get('default_branch')}\n"
                f"URL: {d.get('html_url')}\n"
            )
            return text

    return None


@agent.tool_plain
async def fetch_page(url: str, start: int = 0) -> str:
    """Fetch and read the content of a webpage. Use after web_search for full writeup/CVE details.
    GitHub URLs (tree/blob/repo) are handled via the GitHub API for clean output.
    If the content is truncated, call again with start=8000 to get the next chunk, and so on."""
    q = _status_q.get()
    if q is not None:
        label = url.split('//')[-1][:60]
        q.put_nowait(('status', f'reading: `{label}`'))
        await asyncio.sleep(0)
    try:
        # GitHub-specific fast path
        if "github.com" in url:
            result = await _fetch_github(url, start)
            if result is not None:
                return result

        async with httpx.AsyncClient(headers=_BROWSER_HEADERS, follow_redirects=True, timeout=15) as client:
            resp = await client.get(url)
            resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        chunk = text[start:start + 8000]
        if not chunk:
            return "No more content at this offset."
        if start + 8000 < len(text):
            chunk += f"\n...[truncated — call fetch_page with start={start + 8000} for more]"
        return chunk
    except Exception as e:
        return f"Failed to fetch page: {e}"


@agent.tool_plain
async def get_upcoming_ctfs() -> str:
    """Fetch upcoming CTF competitions from CTFtime (next 4 weeks).
    Returns event names, dates (MYT), format, weight, and CTFtime URL.
    This is READ-ONLY."""
    from handlers.ctf import fetch_upcoming_events
    from utils import convert_to_myt
    q = _status_q.get()
    if q is not None:
        q.put_nowait(('status', 'fetching upcoming CTFs from CTFtime...'))
        await asyncio.sleep(0)
    try:
        events = await fetch_upcoming_events()
    except Exception as e:
        return f"Failed to fetch CTFtime: {e}"
    if not events:
        return "No upcoming CTF events in the next 4 weeks."
    lines = []
    for ev in events:
        try:
            start = datetime.fromisoformat(convert_to_myt(ev["start"])).strftime("%Y-%m-%d %H:%M MYT")
            end = datetime.fromisoformat(convert_to_myt(ev["finish"])).strftime("%Y-%m-%d %H:%M MYT")
        except Exception:
            start = ev.get("start", "?")
            end = ev.get("finish", "?")
        dur = ev.get("duration", {})
        dur_str = f"{dur.get('days', 0)}d {dur.get('hours', 0)}h"
        lines.append(
            f"**{ev['title']}** (ID: {ev['id']})\n"
            f"  Format: {ev.get('format', '?')} | Weight: {ev.get('weight', '?')} | Duration: {dur_str}\n"
            f"  Start: {start}\n"
            f"  End:   {end}\n"
            f"  URL: {ev.get('url', '')}"
        )
    return "\n\n".join(lines)


def strip_tables(text: str) -> str:
    """Convert markdown tables to bullet lists so Discord renders them properly."""
    lines = text.split("\n")
    result = []
    headers = []
    in_table = False

    for line in lines:
        stripped = line.strip()
        # separator row (e.g. |---|---|)
        if re.match(r"^\|[-| :]+\|$", stripped):
            in_table = True
            continue
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped[1:-1].split("|")]
            if not in_table and not headers:
                # first row = headers
                headers = cells
            else:
                # data row — emit as bullet
                if headers and len(cells) == len(headers):
                    parts = [f"**{h}:** {v}" for h, v in zip(headers, cells) if v]
                else:
                    parts = [c for c in cells if c]
                result.append("- " + ", ".join(parts))
            continue
        # non-table line resets state
        if in_table or headers:
            in_table = False
            headers = []
        result.append(line)

    return "\n".join(result)


async def stream_agent_message(channel_id: int, user_message: str):
    """Async generator that yields ('text', delta) or ('status', msg) tuples.

    Times out only if no token/status arrives for 180 s — active tool chains
    never trigger the timeout.  The producer runs in its own task so anyio
    cancel scopes are never crossed between tasks.
    """
    INACTIVITY_TIMEOUT = 180  # Bonsai built-in web search alone can burn 30-40s silently

    _SENTINEL = object()
    queue: asyncio.Queue = asyncio.Queue()

    # Set the status queue in context BEFORE creating the task so the task
    # (and any coroutines it awaits, including async tools) inherits it.
    token = _status_q.set(queue)

    async def _producer():
        try:
            async with agent.run_stream(user_message, message_history=_history[channel_id]) as result:
                async for delta in result.stream_text(delta=True):
                    await queue.put(('text', delta))
                new_msgs = result.new_messages()
            _history[channel_id].extend(new_msgs)
        except Exception as exc:  # noqa: BLE001
            await queue.put(exc)
        finally:
            await queue.put(_SENTINEL)

    producer_task = asyncio.create_task(_producer())
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=INACTIVITY_TIMEOUT)
            except asyncio.TimeoutError:
                yield ('text', '\n\n_timed out waiting for a response_')
                break

            if item is _SENTINEL:
                break
            if isinstance(item, Exception):
                raise item
            yield item  # ('text', str) or ('status', str)
    finally:
        _status_q.reset(token)
        producer_task.cancel()
        try:
            await producer_task
        except (asyncio.CancelledError, Exception):
            pass


async def handle_agent_message(channel_id: int, user_message: str) -> str:
    try:
        async with asyncio.timeout(45):
            async with agent.run_stream(user_message, message_history=_history[channel_id]) as result:
                output = await result.get_output()
                new_msgs = result.new_messages()
            _history[channel_id].extend(new_msgs)
            return strip_tables(output)
    except asyncio.TimeoutError:
        return "took too long, try again"


def clear_channel_history(channel_id: int) -> None:
    _history.pop(channel_id, None)
