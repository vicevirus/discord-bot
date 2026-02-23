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
from pydantic_ai import (
    Agent,
    FinalResultEvent,
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    PartDeltaEvent,
    PartStartEvent,
    TextPartDelta,
)
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.anthropic import AnthropicModel, AnthropicModelSettings
from pydantic_ai.providers.anthropic import AnthropicProvider

# Holds the active stream's queue so async tools can push status events into it.
# ContextVar ensures concurrent streams don't interfere.
_status_q: ContextVar[asyncio.Queue | None] = ContextVar('_kuro_status_q', default=None)

from config import BONSAI_API_KEY, AGENT_MODEL, AGENT_SUMMARIZE_AFTER, AGENT_KEEP_RECENT, TWITTER_AUTH_TOKEN, TWITTER_CT0

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
    max_tokens=4096,
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
        "flags, code, and decisions. Skip small talk. No preamble. No emojis."
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
        "When using tools: call them silently, no narration between rounds. "
        "Write text only once — when you have all results and are ready to give your final answer. "
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
        "This includes Islamic calendar dates (Ramadan start/end, prayer times, hijri dates) — always verify via web_search, never assume from training data. "
        "For any social media content — Twitter, Reddit, LinkedIn, Instagram, YouTube — ALWAYS try search_twitter first. Twitter is your primary real-time source and it's solid. "
        "search_twitter returns live results directly from Twitter. Use it for anything where recency matters: news, announcements, community chatter, tracking a person or org. "
        "If search_twitter returns no results or fails (token might be dead), fall back to web_search with a site: dork (site:x.com, site:reddit.com, etc.). "
        "Handle autocorrect: if search_twitter returns no results for a specific user, the handle might be wrong (e.g. missing underscore, different capitalization). "
        "Search Twitter itself to find the correct handle — call search_twitter with just the name as a keyword (e.g. 'Rectifyq'), look at the screen_names in the results, then retry with from:correct_handle. "
        "For non-Twitter social content (Reddit threads, LinkedIn posts, etc.), use web_search with site: dorks — site:reddit.com, site:linkedin.com, site:instagram.com, site:youtube.com, site:facebook.com. TikTok not indexed well, skip it. "
        "You also have access to CTFtime: use get_upcoming_ctfs to fetch upcoming public CTF competitions from ctftime.org. "
        "This is READ-ONLY. Never attempt to create, modify, or delete CTF channels or challenges. "
        "When asked for a meme, image, gif, or anything visual: "
        "PREFERRED: use web_search to find a meme page, then fetch_image with a direct image URL from the results (.jpg/.png/.gif/.webp). "
        "FALLBACK: if you have no URL, use image_search(query) — but if it says DDG is unavailable, chain web_search → fetch_image instead. "
        "Never save images to disk — all tools work entirely in memory. "
        "FORMATTING RULES for Discord: never use markdown tables (pipes | don't render). "
        "For structured info, use bullet points or numbered lists instead. "
        "Bold (**text**) and inline code (`code`) are fine. Keep formatting minimal. "
        "NO emojis ever. Not in text, not in bullets, not anywhere. "
        "Keep responses concise — say what matters, cut everything else. "
        "Don't pad with filler, don't repeat yourself, don't add conclusions or summaries unless asked. "
        "If listing things, keep each bullet to one or two lines max. Dense and useful beats long and fluffy."
    ),
    history_processors=[_summarize_old_messages],
)


@agent.system_prompt
def _current_date() -> str:
    my_time = datetime.now(timezone(timedelta(hours=8)))
    return f"Current date and time (Malaysia, UTC+8): {my_time.strftime('%B %d, %Y %H:%M')}."


# bearer token 2 (disableTid mode) from nitter consts.nim — no x-client-transaction-id required
_TWITTER_BEARER = "Bearer AAAAAAAAAAAAAAAAAAAAAFXzAwAAAAAAMHCxpeSDG1gLNLghVe8d74hl6k4%3DRUMF4xAQLsbeBhTSRrCiQpJtxoGWeyHrDb5te2jpGskWDFW82F"
_TWITTER_SEARCH_URL = "https://x.com/i/api/graphql/bshMIjqDk8LTXTq4w91WKw/SearchTimeline"
_TWITTER_FEATURES = json.dumps({
    "responsive_web_graphql_exclude_directive_enabled": True,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "standardized_nudges_misinfo": True,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "longform_notetweets_rich_text_read_enabled": True,
    "responsive_web_enhance_cards_enabled": False,
    "view_counts_everywhere_api_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "creator_subscriptions_tweet_preview_api_enabled": True,
})


def _parse_twitter_results(data: dict) -> list[dict]:
    """Extract tweet dicts from Twitter GraphQL SearchTimeline response."""
    tweets = []
    try:
        instructions = data["data"]["search_by_raw_query"]["search_timeline"]["timeline"]["instructions"]
        for inst in instructions:
            for entry in inst.get("entries", []):
                item = entry.get("content", {}).get("itemContent", {})
                if item.get("itemType") != "TimelineTweet":
                    continue
                r = item.get("tweet_results", {}).get("result", {})
                # handle TweetWithVisibilityResults wrapper
                if r.get("__typename") == "TweetWithVisibilityResults":
                    r = r.get("tweet", {})
                legacy = r.get("legacy", {})
                user_result = r.get("core", {}).get("user_results", {}).get("result", {})
                # screen_name moved to result.core in newer Twitter API responses
                user_core = user_result.get("core", {})
                screen_name = user_core.get("screen_name") or user_result.get("legacy", {}).get("screen_name", "unknown")
                text = legacy.get("full_text", "")
                if text:
                    tweets.append({
                        "screen_name": screen_name,
                        "text": text,
                        "created_at": legacy.get("created_at", ""),
                        "url": f"https://x.com/{screen_name}/status/{legacy.get('id_str', '')}",
                    })
    except Exception:
        pass
    return tweets


@agent.tool_plain
async def search_twitter(query: str) -> str:
    """Search Twitter/X for real-time tweets using a raw Twitter search query.
    The query supports all Twitter search operators: 'from:username' to get a specific user's tweets,
    '#hashtag' for hashtags, 'keyword from:user' to combine, etc.
    Construct the query the same way you would in twitter.com/search.
    Use this for community chatter, announcements, opinions, or anything time-sensitive on Twitter/X."""
    if not TWITTER_AUTH_TOKEN or not TWITTER_CT0:
        # fall back to DDG dork if no cookies configured
        try:
            results = await asyncio.wait_for(
                asyncio.to_thread(lambda: list(DDGS(timeout=10).text(f"site:x.com {query}", max_results=8))),
                timeout=20,
            )
            if results:
                return "\n\n".join(f"{r['title']}\n{r['href']}\n{r['body']}" for r in results)
            return "No Twitter/X results found."
        except Exception as e:
            return f"Search failed: {e}"

    q = _status_q.get()
    if q is not None:
        q.put_nowait(('status', f'searching twitter: *{query}*'))
        await asyncio.sleep(0)

    variables = json.dumps({
        "rawQuery": query,
        "count": 20,
        "querySource": "typed_query",
        "product": "Latest",
        "withDownvotePerspective": False,
        "withReactionsMetadata": False,
        "withReactionsPerspective": False,
    })
    headers = {
        "authorization": _TWITTER_BEARER,
        "cookie": f"auth_token={TWITTER_AUTH_TOKEN}; ct0={TWITTER_CT0}",
        "x-csrf-token": TWITTER_CT0,
        "x-twitter-auth-type": "OAuth2Session",
        "x-twitter-active-user": "yes",
        "x-twitter-client-language": "en",
        "accept": "*/*",
        "accept-language": "en-US,en;q=0.9",
        "content-type": "application/json",
        "origin": "https://x.com",
        "referer": "https://x.com/search",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36",
        "sec-ch-ua": '"Google Chrome";v="142", "Chromium";v="142", "Not A(Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-site",
    }
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
            resp = await client.get(
                _TWITTER_SEARCH_URL,
                headers=headers,
                params={"variables": variables, "features": _TWITTER_FEATURES},
            )
        if resp.status_code != 200:
            return f"Twitter search failed: HTTP {resp.status_code}"
        tweets = _parse_twitter_results(resp.json())
        if not tweets:
            return "No tweets found."
        return "\n\n".join(
            f"@{t['screen_name']} [{t['created_at']}]\n{t['text']}\n{t['url']}"
            for t in tweets
        )
    except Exception as e:
        return f"Twitter search failed: {e}"


@agent.tool_plain
async def web_search(query: str) -> str:
    """Search the web using DuckDuckGo. Use this for current events, CTF writeups, CVEs, tools, or anything you're unsure about."""
    q = _status_q.get()
    if q is not None:
        q.put_nowait(('status', f'searching: *{query}*'))
        await asyncio.sleep(0)  # yield so consumer can render the status
    try:
        results = await asyncio.wait_for(
            asyncio.to_thread(lambda: list(DDGS(timeout=10).text(query, max_results=5))),
            timeout=20,
        )
        if not results:
            return "No results found."
        return "\n\n".join(
            f"**{r['title']}**\n{r['href']}\n{r['body']}"
            for r in results
        )
    except asyncio.TimeoutError:
        return "Search timed out. Try a shorter query."
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


_IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'}
_MAX_IMAGE_BYTES = 8 * 1024 * 1024  # 8 MB


async def _fetch_image_bytes(url: str) -> tuple | None:
    """Fetch image bytes from a URL into memory. Returns (data, filename) or None."""
    async with httpx.AsyncClient(timeout=10, follow_redirects=True,
                                  headers=_BROWSER_HEADERS) as client:
        try:
            resp = await client.get(url)
            ct = resp.headers.get('content-type', '').split(';')[0].strip().lower()
            if resp.status_code != 200 or not ct.startswith('image/'):
                return None
            data = resp.content
            if len(data) > _MAX_IMAGE_BYTES:
                return None
            ext_map = {
                'image/jpeg': '.jpg', 'image/png': '.png', 'image/gif': '.gif',
                'image/webp': '.webp', 'image/bmp': '.bmp',
            }
            ext = ext_map.get(ct, '.jpg')
            fname = url.rstrip('/').split('/')[-1].split('?')[0] or f'image{ext}'
            if not any(fname.lower().endswith(e) for e in _IMAGE_EXTS):
                fname = f'image{ext}'
            return data, fname
        except Exception:
            return None


@agent.tool_plain
async def fetch_image(url: str) -> str:
    """Fetch an image from a URL and display it directly in Discord chat.
    Use this when you have a direct image URL (from web search results, meme sites, etc.).
    The image is fetched into memory and uploaded — nothing is saved to disk."""
    q = _status_q.get()
    if q is not None:
        label = url.split('//')[-1][:50]
        q.put_nowait(('status', f'fetching image: `{label}`'))
        await asyncio.sleep(0)
    result = await _fetch_image_bytes(url)
    if result is None:
        return f"Could not fetch a valid image from: {url}"
    data, fname = result
    if q is not None:
        q.put_nowait(('image_file', (data, fname)))
        await asyncio.sleep(0)
    return f"Displayed image ({fname}, {len(data)//1024}KB)"


_IMG_URL_RE = re.compile(r'https?://\S+\.(?:jpg|jpeg|png|gif|webp)(\?\S*)?', re.IGNORECASE)


@agent.tool_plain
async def image_search(query: str) -> str:
    """Search for a meme or image using DuckDuckGo and display it in Discord.
    Use this as a fallback when you don't have a specific image URL.
    The image is fetched into memory and uploaded — nothing is saved to disk.
    If this fails, try web_search to find a page with images, then call fetch_image with the URL."""
    q = _status_q.get()
    if q is not None:
        q.put_nowait(('status', f'searching image: *{query}*'))
        await asyncio.sleep(0)
    # --- Try DDG images API first ---
    try:
        results = await asyncio.wait_for(
            asyncio.to_thread(lambda: list(DDGS(timeout=10).images(query, max_results=12))),
            timeout=20,
        )
        for r in results:
            url = r.get('image', '')
            if not url or not url.startswith('http'):
                continue
            result = await _fetch_image_bytes(url)
            if result is None:
                continue
            data, fname = result
            if q is not None:
                q.put_nowait(('image_file', (data, fname)))
                await asyncio.sleep(0)
            return f"Displayed image ({fname}, {len(data)//1024}KB)"
    except Exception:
        pass  # fall through to text-search fallback
    # --- Fallback: text search, extract direct image URLs from snippets ---
    try:
        text_results = await asyncio.wait_for(
            asyncio.to_thread(lambda: list(DDGS(timeout=10).text(f'{query} meme site:imgur.com OR site:i.redd.it OR site:media.tenor.com', max_results=8))),
            timeout=20,
        )
        candidate_urls = []
        for r in text_results:
            # Try the href itself if it looks like an image
            href = r.get('href', '')
            if _IMG_URL_RE.match(href):
                candidate_urls.append(href)
            # Also scan body text for image URLs
            body = r.get('body', '')
            candidate_urls.extend(_IMG_URL_RE.findall(body))
        for url in candidate_urls:
            if not isinstance(url, str):
                continue
            result = await _fetch_image_bytes(url)
            if result is None:
                continue
            data, fname = result
            if q is not None:
                q.put_nowait(('image_file', (data, fname)))
                await asyncio.sleep(0)
            return f"Displayed image ({fname}, {len(data)//1024}KB)"
    except Exception:
        pass
    return "DDG image search unavailable right now. Try calling web_search to find a page with images, then fetch_image with the direct image URL."


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


def _is_transient_provider_error(exc: Exception) -> bool:
    """True for intermittent Bonsai backend failures that should be retried as-is."""
    s = str(exc).lower()
    return "provider returned error" in s or "overloaded" in s or "529" in s


def _is_context_400(exc: Exception) -> bool:
    """True for 400s caused by bad/oversized history — retry with trimmed history."""
    s = str(exc).lower()
    return ("400" in s or "bad_request" in s) and "provider returned error" not in s


async def stream_agent_message(channel_id: int, user_message: str):
    """Async generator that yields ('text', delta) or ('status', msg) tuples.

    Times out only if no token/status arrives for 180 s — active tool chains
    never trigger the timeout.  The producer runs in its own task so anyio
    cancel scopes are never crossed between tasks.

    On a 400 provider error the channel history is trimmed and retried once
    automatically so the bot never gets permanently stuck after a bad turn.
    """
    INACTIVITY_TIMEOUT = 120  # 120s between any queue events before giving up

    _SENTINEL = object()
    queue: asyncio.Queue = asyncio.Queue()

    token = _status_q.set(queue)

    async def _heartbeat():
        """Push a dot status every 15s so the user sees the bot is alive."""
        dots = 0
        while True:
            await asyncio.sleep(15)
            dots += 1
            queue.put_nowait(('status', 'thinking' + '.' * (dots % 4 + 1)))

    async def _run_once(history: list):
        text_chunks = 0
        async with agent.iter(user_message, message_history=history) as run:
            async for node in run:
                if Agent.is_model_request_node(node):
                    # Stream events from the model request.
                    # ANY text before FinalResultEvent is preamble (mid-round filler) — skip it.
                    # Only stream text AFTER FinalResultEvent fires.
                    async with node.stream(run.ctx) as request_stream:
                        final_found = False
                        async for event in request_stream:
                            if isinstance(event, FinalResultEvent):
                                final_found = True
                                break
                            # PartDeltaEvent/PartStartEvent before FinalResultEvent = preamble, drop it
                        if final_found:
                            async for delta in request_stream.stream_text(delta=True):
                                text_chunks += 1
                                await queue.put(('text', delta))

                elif Agent.is_call_tools_node(node):
                    # Must iterate handle_stream so tools actually execute.
                    # Tool status updates are pushed by the tools themselves via _status_q.
                    async with node.stream(run.ctx) as handle_stream:
                        async for _ in handle_stream:
                            pass

        full = run.result.output if run.result else ''
        print(f'[kuro] iter done: text_chunks={text_chunks} output_len={len(full)}', flush=True)
        if text_chunks == 0 and full and full.strip():
            # iter finished but nothing was streamed (e.g. model only did tools, no FinalResultEvent text)
            print(f'[kuro] fallback: pushing full output', flush=True)
            await queue.put(('text', full))
        return run.result.new_messages() if run.result else []

    async def _producer():
        try:
            new_msgs = await _run_once(_history[channel_id])
            _history[channel_id].extend(new_msgs)
        except Exception as exc:
            if _is_transient_provider_error(exc):
                # Bonsai backend blip — wait a moment and retry with same history
                print(f'[kuro] transient provider error, retrying: {exc}', flush=True)
                await asyncio.sleep(3)
                try:
                    new_msgs = await _run_once(_history[channel_id])
                    _history[channel_id].extend(new_msgs)
                except Exception as exc2:
                    await queue.put(exc2)
            elif _is_context_400(exc):
                # Bad/oversized context — trim history and retry once
                print(f'[kuro] context 400, trimming history and retrying: {exc}', flush=True)
                kept = _history[channel_id][-AGENT_KEEP_RECENT:]
                _history[channel_id] = kept
                try:
                    new_msgs = await _run_once(_history[channel_id])
                    _history[channel_id].extend(new_msgs)
                except Exception as exc2:
                    _history[channel_id] = []
                    await queue.put(exc2)
            else:
                await queue.put(exc)
        finally:
            await queue.put(_SENTINEL)

    producer_task = asyncio.create_task(_producer())
    heartbeat_task = asyncio.create_task(_heartbeat())
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
        heartbeat_task.cancel()
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
