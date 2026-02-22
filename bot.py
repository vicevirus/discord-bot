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
    slash_delete_writeup,
    writeup_autocomplete,
    slash_batch_delete_writeup,
    author_autocomplete,
    # Anonymous handler
    handle_anonymous_question,
    # Help
    send_help_message,
    send_writeup_help,
    SLASH_HELP_MESSAGE,
    SLASH_WRITEUP_HELP_MESSAGE,
    # Challenge tracking
    handle_chall_create,
    handle_chall_solved,
    handle_chall_working,
    handle_chall_unsolved,
    handle_chall_status,
    # Agent (Kuro)
    handle_agent_message,
    stream_agent_message,
    strip_tables,
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
        # Copy global commands to the guild for instant sync
        bot.tree.copy_global_to(guild=guild)
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


@bot.tree.command(name="chall", description="Create a challenge thread")
@discord.app_commands.describe(
    category="Challenge category (web, pwn, crypto, rev, misc, forensics, etc.)",
    name="Challenge name"
)
async def slash_chall(interaction: discord.Interaction, category: str, name: str):
    """Slash command: /chall <category> <name>"""
    from handlers.challenge import create_challenge_thread
    await create_challenge_thread(interaction, category, name)


@bot.tree.command(name="solved", description="Mark challenge as solved (use in challenge thread)")
async def slash_solved(interaction: discord.Interaction):
    """Slash command: /solved"""
    from handlers.challenge import mark_solved
    await mark_solved(interaction)


@bot.tree.command(name="unsolved", description="Reset challenge to unsolved")
async def slash_unsolved(interaction: discord.Interaction):
    """Slash command: /unsolved"""
    from handlers.challenge import mark_unsolved
    await mark_unsolved(interaction)


@bot.tree.command(name="status", description="Show all challenges and progress")
async def slash_status(interaction: discord.Interaction):
    """Slash command: /status"""
    from handlers.challenge import show_status
    await show_status(interaction)


@bot.tree.command(name="delchall", description="Delete this challenge (creator/admin only)")
async def slash_delchall(interaction: discord.Interaction):
    """Slash command: /delchall"""
    from handlers.challenge import delete_challenge
    await delete_challenge(interaction)


@bot.tree.command(name="delwriteup", description="Delete a writeup (author/admin only)")
@discord.app_commands.describe(
    writeup="Select the writeup to delete"
)
@discord.app_commands.autocomplete(writeup=writeup_autocomplete)
async def slash_delwriteup(interaction: discord.Interaction, writeup: str):
    """Slash command: /delwriteup"""
    await slash_delete_writeup(interaction, writeup)


@bot.tree.command(name="delwriteups", description="[ADMIN] Batch delete all writeups by a user")
@discord.app_commands.describe(
    username="Discord username whose writeups to delete"
)
@discord.app_commands.autocomplete(username=author_autocomplete)
async def slash_delwriteups(interaction: discord.Interaction, username: str):
    """Slash command: /delwriteups (admin only)"""
    await slash_batch_delete_writeup(interaction, username)


# =============================================================================
# MESSAGE HANDLER
# =============================================================================

@bot.event
async def on_message(message):
    """Main message handler for all prefix commands."""
    current_year = get_current_year()
    
    # =================================
    # AUTO-TRACK CHALLENGE WORKERS
    # =================================
    # Anyone chatting in a challenge thread = working on it
    if isinstance(message.channel, discord.Thread) and not message.author.bot:
        from handlers.challenge import auto_track_worker
        await auto_track_worker(message)
    
    # =================================
    # KURO @MENTION IN CHANNELS
    # =================================
    if (
        not isinstance(message.channel, discord.DMChannel)
        and not message.author.bot
        and bot.user in message.mentions
    ):
        user_input = message.content.replace(f'<@{bot.user.id}>', '').replace(f'<@!{bot.user.id}>', '').strip()
        if user_input:
            sent = await message.channel.send('▍')
            accumulated = ''
            current_status = ''
            loop = asyncio.get_event_loop()
            last_edit = loop.time()

            try:
                async with message.channel.typing():
                    async for event in stream_agent_message(message.channel.id, user_input):
                        kind, data = event
                        if kind == 'status':
                            current_status = data
                            # Show status immediately regardless of throttle
                            base = strip_tables(accumulated)
                            preview = (base[:1820] + '...') if len(base) > 1820 else base
                            sep = '\n\n' if preview else ''
                            try:
                                await sent.edit(content=f'{preview}{sep}_{current_status}_')
                            except Exception:
                                pass
                        elif kind == 'text':
                            accumulated += data
                            current_status = ''  # clear status once text starts flowing
                            now = loop.time()
                            if now - last_edit >= 1.0 and accumulated.strip():
                                preview = strip_tables(accumulated)
                                display = preview[:1897] + '...' if len(preview) > 1900 else preview
                                try:
                                    await sent.edit(content=display + ' ▍')
                                except Exception:
                                    pass
                                last_edit = now
            except Exception as e:
                await sent.edit(content=f'error: {e}')
                return

            final = strip_tables(accumulated)
            if not final.strip():
                await sent.edit(content='...')
            elif len(final) <= 1900:
                await sent.edit(content=final)
            else:
                chunks = [final[i:i+1900] for i in range(0, len(final), 1900)]
                await sent.edit(content=chunks[0])
                for chunk in chunks[1:]:
                    await message.channel.send(chunk)
        return

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

        # Any other DM — talk to Kuro
        else:
            user_input = message.content.strip()
            if user_input:
                sent = await message.channel.send('▍')
                accumulated = ''
                current_status = ''
                loop = asyncio.get_event_loop()
                last_edit = loop.time()

                try:
                    async with message.channel.typing():
                        async for event in stream_agent_message(message.channel.id, user_input):
                            kind, data = event
                            if kind == 'status':
                                current_status = data
                                base = strip_tables(accumulated)
                                preview = (base[:1820] + '...') if len(base) > 1820 else base
                                sep = '\n\n' if preview else ''
                                try:
                                    await sent.edit(content=f'{preview}{sep}_{current_status}_')
                                except Exception:
                                    pass
                            elif kind == 'text':
                                accumulated += data
                                current_status = ''
                                now = loop.time()
                                if now - last_edit >= 1.0 and accumulated.strip():
                                    preview = strip_tables(accumulated)
                                    display = preview[:1897] + '...' if len(preview) > 1900 else preview
                                    try:
                                        await sent.edit(content=display + ' ▍')
                                    except Exception:
                                        pass
                                    last_edit = now
                except Exception as e:
                    await sent.edit(content=f'error: {e}')
                    return

                final = strip_tables(accumulated)
                if not final.strip():
                    await sent.edit(content='...')
                elif len(final) <= 1900:
                    await sent.edit(content=final)
                else:
                    chunks = [final[i:i+1900] for i in range(0, len(final), 1900)]
                    await sent.edit(content=chunks[0])
                    for chunk in chunks[1:]:
                        await message.channel.send(chunk)

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
    elif message.content.startswith('>writeup '):
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
    # CHALLENGE TRACKING
    # =================================
    elif message.content.startswith('>chall '):
        try:
            await handle_chall_create(message)
        except Exception as e:
            await message.channel.send(f"❌ Failed to create challenge: {str(e)}")
    
    elif message.content.strip() == '>solved':
        try:
            await handle_chall_solved(message)
        except Exception as e:
            await message.channel.send(f"❌ Failed to mark solved: {str(e)}")
    
    elif message.content.strip() == '>working':
        try:
            await handle_chall_working(message)
        except Exception as e:
            await message.channel.send(f"❌ Failed to mark working: {str(e)}")
    
    elif message.content.strip() == '>unsolved':
        try:
            await handle_chall_unsolved(message)
        except Exception as e:
            await message.channel.send(f"❌ Failed to mark unsolved: {str(e)}")
    
    elif message.content.strip() == '>status':
        try:
            await handle_chall_status(bot, message)
        except Exception as e:
            await message.channel.send(f"❌ Failed to get status: {str(e)}")
    
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
