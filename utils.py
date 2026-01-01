"""
Utility functions for the Discord bot.
"""

import re
import pytz
from datetime import datetime


def normalize_name(text):
    """Convert text to lowercase alphanumeric only (for file names)."""
    return re.sub(r'[^a-z0-9]', '', text.lower())


def convert_to_myt(utc_time_str):
    """Convert UTC time string to Malaysia Time (MYT)."""
    utc_time = datetime.fromisoformat(utc_time_str.replace('Z', '+00:00'))
    return utc_time.astimezone(pytz.timezone('Asia/Kuala_Lumpur')).isoformat()


def is_ctf_channel(channel):
    """Check if channel (or thread's parent) is in a CTF or archive category."""
    import discord
    
    # If it's a thread, check the parent channel
    if isinstance(channel, discord.Thread):
        channel = channel.parent
    
    if not channel or not channel.category:
        return False
    cat_name = channel.category.name
    return cat_name.startswith("ctf-") or cat_name.startswith("archive-")
