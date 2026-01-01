"""
CTF-related handlers: create, archive, upcoming events.
"""

import discord
import aiohttp
import asyncio
import io
import random
from datetime import datetime, timedelta
from PIL import Image

from config import (
    CTFTIME_HEADERS,
    CTF_ANNOUNCE_CHANNEL_ID,
    SERVER_ID,
)
from utils import convert_to_myt


# Track current year (updated by background task)
current_year = datetime.now().year
current_year_short = str(current_year)[-2:]


def get_current_year():
    """Get current year value."""
    return current_year


def get_current_year_short():
    """Get current year short value (e.g., '26' for 2026)."""
    return current_year_short


def update_year():
    """Update year tracking when year changes."""
    global current_year, current_year_short
    current_year = datetime.now().year
    current_year_short = str(current_year)[-2:]


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

async def fetch_image(url):
    """Fetch and return an image from URL."""
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                return Image.open(io.BytesIO(await response.read()))
            return None


async def create_category_if_not_exists(guild, category_name):
    """Create a category if it doesn't exist, return existing otherwise."""
    category = discord.utils.get(guild.categories, name=category_name)
    return category or await guild.create_category(category_name)


async def move_channel_to_archive(channel):
    """Move a channel to the archive category."""
    archive_category = await create_category_if_not_exists(
        channel.guild, f'archive-{current_year}'
    )
    await channel.edit(category=archive_category)
    print(f"Moved channel {channel.name} to {archive_category.name}")


# =============================================================================
# CTFTIME API
# =============================================================================

async def fetch_event_details(event_id):
    """Fetch event details from CTFtime API."""
    url = f'https://ctftime.org/api/v1/events/{event_id}/'
    timeout = aiohttp.ClientTimeout(total=30)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=CTFTIME_HEADERS) as response:
                return await response.json() if response.status == 200 else None
    except asyncio.TimeoutError:
        print(f"Timeout fetching event {event_id}")
        return None


async def fetch_upcoming_events():
    """Fetch upcoming CTF events from CTFtime (next 2 weeks, limit 5)."""
    start = int(datetime.now().timestamp())
    end = int((datetime.now() + timedelta(weeks=2)).timestamp())
    url = f'https://ctftime.org/api/v1/events/?limit=5&start={start}&finish={end}'
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=CTFTIME_HEADERS) as response:
            return await response.json() if response.status == 200 else None


# =============================================================================
# CTF CHANNEL CREATION
# =============================================================================

async def create_channel_and_event(bot, guild, event):
    """Create a CTF channel and scheduled event from CTFtime event data."""
    category_name = f'ctf-{current_year}'
    channel_name = event['title'].lower().replace(' ', '-')
    
    # Check for duplicate
    category = await create_category_if_not_exists(guild, category_name)
    for channel in category.channels:
        if channel.name == channel_name:
            return None, f"Cannot create CTF '{event['title']}', duplicate event.", None
    
    # Create role for CTF participants
    role_name = f"{event['title']} {current_year_short}"
    interested_role = await guild.create_role(
        name=role_name,
        colour=discord.Colour(0x0000FF),
        mentionable=True,
        reason=f"Role for {event['title']} CTF event"
    )
    
    # Create channel with role-based permissions
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        interested_role: discord.PermissionOverwrite(view_channel=True, send_messages=True)
    }
    channel = await guild.create_text_channel(
        channel_name, category=category, overwrites=overwrites
    )
    
    # Prepare event times
    start_time_myt = convert_to_myt(event['start'])
    finish_time_myt = convert_to_myt(event['finish'])
    
    # Fetch event logo or use default
    image = await fetch_image(event['logo']) if event.get('logo') else None
    if image is None:
        default_logo = "https://raw.githubusercontent.com/vicevirus/front-end-ctf-sharing-materials/main/ctf_event.png"
        image = await fetch_image(default_logo)
    
    # Convert image to bytes
    with io.BytesIO() as image_binary:
        image.save(image_binary, format='PNG')
        image_binary.seek(0)
        image_bytes = image_binary.read()
    
    # Truncate description if too long
    description = event['description']
    if len(description) > 1000:
        description = description[:997] + '...'
    
    # Create scheduled event
    await guild.create_scheduled_event(
        name=event['title'],
        start_time=datetime.fromisoformat(start_time_myt),
        end_time=datetime.fromisoformat(finish_time_myt),
        description=description,
        entity_type=discord.EntityType.external,
        privacy_level=discord.PrivacyLevel.guild_only,
        location=event['url'],
        image=image_bytes
    )
    
    # Announce CTF creation
    announce_channel = bot.get_channel(CTF_ANNOUNCE_CHANNEL_ID)
    if not announce_channel:
        return channel, None, interested_role
    
    ctf_message = await announce_channel.send(
        f"@everyone Successfully created CTF \"{event['title']}\"! "
        f"React with 👍 if you're playing or want to access the channel."
    )
    await ctf_message.add_reaction("👍")
    
    return channel, ctf_message, interested_role


# =============================================================================
# DISPLAY UPCOMING CTFS
# =============================================================================

async def display_upcoming_ctfs(message):
    """Display upcoming CTF events."""
    events = await fetch_upcoming_events()
    
    if not events:
        await message.channel.send("No upcoming CTF events found.")
        return
    
    seen_event_ids = set()
    
    for event in events:
        if event['id'] in seen_event_ids:
            continue
        seen_event_ids.add(event['id'])
        
        # Format times
        start_time = convert_to_myt(event['start'])
        end_time = convert_to_myt(event['finish'])
        start_formatted = datetime.fromisoformat(start_time).strftime('%Y-%m-%d %H:%M:%S MYT')
        end_formatted = datetime.fromisoformat(end_time).strftime('%Y-%m-%d %H:%M:%S MYT')
        duration = f"{event['duration']['days']}d {event['duration']['hours']}h"
        
        # Build embed
        event_embed = discord.Embed(
            title=event['title'],
            description=(
                f"**Event ID:** {event['id']}\n"
                f"**Weight:** {event['weight']}\n"
                f"**Duration:** {duration}\n"
                f"**Start Time:** {start_formatted}\n"
                f"**End Time:** {end_formatted}\n"
                f"**Format:** {event['format']}\n"
                f"**[More Info]({event['url']})**"
            ),
            color=random.randint(0, 0xFFFFFF)
        )
        
        if event['logo']:
            event_embed.set_thumbnail(url=event['logo'])
        
        await message.channel.send(embed=event_embed)


# =============================================================================
# COMMAND HANDLERS
# =============================================================================

async def handle_ctf_create(bot, message, event_id):
    """Handle >ctf create command."""
    # Validate event ID is numeric
    if not event_id or not event_id.strip().isdigit():
        await message.channel.send("❌ Invalid event ID. Please provide a numeric CTFtime event ID.\nExample: `>ctf create 12345`")
        return
    
    event = await fetch_event_details(event_id.strip())
    
    if event:
        await create_channel_and_event(bot, message.guild, event)
    else:
        await message.channel.send("❌ Failed to fetch event data. Please check the event ID on ctftime.org.")


async def handle_ctf_archive(message):
    """Handle >ctf archive command."""
    if not message.channel.category:
        await message.channel.send(
            "This command can only be used in channels within the current year's CTF category."
        )
        return
    
    if message.channel.category.name != f'ctf-{current_year}':
        await message.channel.send(
            "This command can only be used in channels within the current year's CTF category."
        )
        return
    
    if not message.author.guild_permissions.administrator:
        await message.channel.send("You do not have permission to archive channels.")
        return
    
    await move_channel_to_archive(message.channel)
    await message.channel.send(f"Channel '{message.channel.name}' has been moved to the archive.")
