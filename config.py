"""
Configuration settings for the Discord bot.
"""

import os
from dotenv import load_dotenv

load_dotenv()


# =============================================================================
# DISCORD SETTINGS
# =============================================================================

DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
SERVER_ID = 1250679106899673121
SPAMMING_CHANNEL_ID = 1250850841385238599
CTF_HELPME_CHANNEL_ID = 1251857136804302969
CTF_ANNOUNCE_CHANNEL_ID = 1251192205381472296


# =============================================================================
# TWITTER / X
# =============================================================================

TWITTER_AUTH_TOKEN = os.getenv("TWITTER_AUTH_TOKEN", "")
TWITTER_CT0 = os.getenv("TWITTER_CT0", "")
OWNER_DISCORD_ID = int(os.getenv("OWNER_DISCORD_ID", "0"))


# =============================================================================
# AI AGENT
# =============================================================================

# Primary: Anthropic-compatible proxy
AGENT_API_KEY = os.getenv("AGENT_API_KEY", "")
AGENT_BASE_URL = os.getenv("AGENT_BASE_URL", "https://gpt.mirbuds.com/claudecode")
AGENT_MODEL = os.getenv("AGENT_MODEL", "claude-sonnet-4-20250514")

# Fallback: OpenRouter
FALLBACK_API_KEY = os.getenv("FALLBACK_API_KEY", os.getenv("OPENROUTER_API_KEY", ""))
FALLBACK_BASE_URL = os.getenv("FALLBACK_BASE_URL", "https://openrouter.ai/api/v1")
FALLBACK_MODEL = os.getenv("FALLBACK_MODEL", "nvidia/nemotron-3-nano-30b-a3b:free")

AGENT_SUMMARIZE_AFTER = 100
AGENT_KEEP_RECENT = 10


# =============================================================================
# TIMING
# =============================================================================

CHECK_INTERVAL = 24 * 60 * 60  # Check for year change every 24 hours


# =============================================================================
# CTFTIME API
# =============================================================================

CTFTIME_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}


# =============================================================================
# WRITEUP PARSING PATTERNS (fuzzy matching)
# =============================================================================

CATEGORY_PATTERNS = ["category:", "cat:", "categ:"]
CHALLENGE_PATTERNS = ["challenge name:", "challenge:", "title:", "name:", "chall:"]
