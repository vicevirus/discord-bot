"""
REUN10N CTF Discord Bot
========================
Main entry point for the Discord bot.

Author: REUN10N Team
"""

import discord
from discord.ext import commands
from discord import app_commands
import asyncio

from config import (
    DISCORD_TOKEN,
    SERVER_ID,
    SPAMMING_CHANNEL_ID,
    CHECK_INTERVAL,
)
from handlers import (
    # CTF handlers
    handle_ctf_create,
    handle_ctf_archive,
    display_upcoming_ctfs,
    create_category_if_not_exists,
    get_current_year,
    get_current_year_short,
    update_year,
    # Writeup handlers
    handle_quick_writeup,
    handle_batch_writeup,
    handle_writeup_delete,
    # Anonymous handler
    handle_anonymous_question,
    # Help
    send_help_message,
    send_writeup_help,
    SLASH_HELP_MESSAGE,
    SLASH_WRITEUP_HELP_MESSAGE,
)


# =============================================================================
# BOT SETUP
# =============================================================================

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.dm_messages = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix='>', intents=intents)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

async def is_member_of_guild(user):
    """Check if user is a member of the main server."""
    guild = bot.get_guild(SERVER_ID)
    return any(member.id == user.id for member in guild.members)


# =============================================================================
# BACKGROUND TASKS
# =============================================================================

async def check_yearly_update():
    """Background task to check for year change and update categories."""
    await bot.wait_until_ready()
    
    while not bot.is_closed():
        from datetime import datetime
        now = datetime.now()
        
        if now.year != get_current_year():
            guild = bot.get_guild(SERVER_ID)
            if guild:
                update_year()
                current_year = get_current_year()
                await create_category_if_not_exists(guild, f'ctf-{current_year}')
                await create_category_if_not_exists(guild, f'archive-{current_year}')
                print(f"Year has changed to {current_year}. Categories updated.")
        
        await asyncio.sleep(CHECK_INTERVAL)


# =============================================================================
# EVENT HANDLERS
# =============================================================================

@bot.event
async def on_ready():
    """Bot startup event."""
    print(f'Logged in as {bot.user}')
    
    guild = bot.get_guild(SERVER_ID)
    current_year = get_current_year()
    
    if guild:
        await create_category_if_not_exists(guild, f'ctf-{current_year}')
        await create_category_if_not_exists(guild, f'archive-{current_year}')
    
    # Sync slash commands to the specific guild for instant availability
    # (global sync can take up to 1 hour to propagate)
    try:
        synced = await bot.tree.sync(guild=guild)
        print(f"Synced {len(synced)} slash command(s) to guild {guild.name}")
    except Exception as e:
        print(f"Failed to sync commands: {e}")
    
    bot.loop.create_task(check_yearly_update())


@bot.event
async def on_raw_reaction_add(payload):
    """Handle reactions to grant CTF channel access."""
    if payload.emoji.name != "👍":
        return
    
    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return
    
    member = guild.get_member(payload.user_id)
    if not member or member.bot:
        return
    
    # Check if reaction is on a bot message
    message = await bot.get_channel(payload.channel_id).fetch_message(payload.message_id)
    if message.author.id != bot.user.id:
        return
    
    # Extract event name and grant role
    try:
        event_name = message.content.split('"')[1]
        role_name = f"{event_name} {get_current_year_short()}"
        role = discord.utils.get(guild.roles, name=role_name)
        
        if role:
            await member.add_roles(role)
            await member.send(f"You have been granted access to the CTF channel for {event_name}.")
    except (IndexError, ValueError):
        pass


# =============================================================================
# SLASH COMMANDS
# =============================================================================

@bot.tree.command(name="help", description="Show bot commands and usage")
async def slash_help(interaction: discord.Interaction):
    """Slash command: /help"""
    await interaction.response.send_message(SLASH_HELP_MESSAGE, ephemeral=True)


@bot.tree.command(name="help-writeup", description="Show detailed writeup command usage")
async def slash_help_writeup(interaction: discord.Interaction):
    """Slash command: /help-writeup"""
    await interaction.response.send_message(SLASH_WRITEUP_HELP_MESSAGE, ephemeral=True)


# =============================================================================
# MESSAGE HANDLER
# =============================================================================

@bot.event
async def on_message(message):
    """Main message handler for all prefix commands."""
    current_year = get_current_year()
    
    # =================================
    # DM COMMANDS
    # =================================
    if isinstance(message.channel, discord.DMChannel) and message.author != bot.user:
        if not await is_member_of_guild(message.author):
            await message.channel.send("You must be a member of the server to use this command.")
            return
        
        # Anonymous question to CTF channel
        if message.content.startswith('>ask ctf '):
            parts = message.content.split(' ')
            if len(parts) > 3:
                await handle_anonymous_question(bot, message, parts[2])
            else:
                await message.channel.send("Usage: >ask ctf <channel_name> <question>")
        
        # Anonymous question to general
        elif message.content.startswith('>ask '):
            await handle_anonymous_question(bot, message)
        
        # Help commands
        elif message.content.startswith('>bot help'):
            parts = message.content.split()
            if len(parts) > 2 and parts[2] == 'writeup':
                await send_writeup_help(message.channel)
            else:
                await send_help_message(message.channel)
    
    # =================================
    # CTF CREATE
    # =================================
    if message.content.startswith('>ctf create ') and message.channel.id == SPAMMING_CHANNEL_ID:
        event_id = message.content[len('>ctf create '):].strip()
        await handle_ctf_create(bot, message, event_id)
    
    # =================================
    # CTF ARCHIVE
    # =================================
    elif message.content.startswith('>ctf archive'):
        await handle_ctf_archive(message)
    
    # =================================
    # CTF UPCOMING
    # =================================
    elif message.content.startswith('>ctf upcoming'):
        await display_upcoming_ctfs(message)
    
    # =================================
    # CTF WRITEUP (BATCH)
    # =================================
    elif message.content.startswith(">ctf writeup"):
        try:
            await handle_batch_writeup(message)
        except Exception as e:
            await message.channel.send(f"❌ Failed to process: {str(e)}")
    
    # =================================
    # QUICK WRITEUP
    # =================================
    elif message.content.startswith('>writeup ') or (
        not message.content.strip() and 
        any(a.filename == 'message.txt' for a in message.attachments)
    ):
        try:
            await handle_quick_writeup(message)
        except Exception as e:
            await message.channel.send(f"❌ Failed to process writeup: {str(e)}")
            print(f"Error processing writeup: {str(e)}")
    
    # =================================
    # WRITEUP DELETE
    # =================================
    elif message.content.startswith('>writeup-delete '):
        try:
            await handle_writeup_delete(message)
        except Exception as e:
            await message.channel.send(f"❌ Failed to delete writeup: {str(e)}")
            print(f"Error deleting writeup: {str(e)}")
    
    # =================================
    # HELP (CHANNEL)
    # =================================
    elif message.content.startswith('>bot help'):
        parts = message.content.split()
        if len(parts) > 2 and parts[2] == 'writeup':
            await send_writeup_help(message.channel)
        else:
            await send_help_message(message.channel)


# =============================================================================
# RUN BOT
# =============================================================================

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
