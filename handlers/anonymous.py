"""
Anonymous question handler.
"""

import discord

from config import SERVER_ID, CTF_HELPME_CHANNEL_ID
from handlers.ctf import get_current_year


async def send_anonymous_message(bot, channel_id, formatted_message, dm_channel):
    """Send a message anonymously to a channel."""
    channel = bot.get_channel(channel_id)
    if channel:
        await channel.send(formatted_message)
        await dm_channel.send(f"Your message has been sent to {channel.name} anonymously.")


async def handle_anonymous_question(bot, message, channel_name=None):
    """Handle anonymous question sending."""
    current_year = get_current_year()
    
    if channel_name:
        question = ' '.join(message.content.split(' ')[3:]).strip()
    else:
        question = message.content[len('>ask '):].strip()
    
    formatted_message = f"**Anon:**\n```markdown\n{question}\n```"
    
    if channel_name:
        guild = bot.get_guild(SERVER_ID)
        channel = discord.utils.get(guild.channels, name=channel_name)
        valid_categories = [f'ctf-{current_year}', f'archive-{current_year}']
        
        if not channel or (channel.category and channel.category.name not in valid_categories):
            await message.channel.send(f"Invalid channel '{channel_name}' for this command.")
            return
        
        await send_anonymous_message(bot, channel.id, formatted_message, message.channel)
    else:
        await send_anonymous_message(bot, CTF_HELPME_CHANNEL_ID, formatted_message, message.channel)
