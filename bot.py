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
import io
import httpx

from config import (
    DISCORD_TOKEN,
    SERVER_ID,
    SPAMMING_CHANNEL_ID,
    CHECK_INTERVAL,
    TWITTER_AUTH_TOKEN,
    TWITTER_CT0,
    OWNER_DISCORD_ID,
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
# SAFE ATTACHMENT READER
# =============================================================================

_MAX_ATTACH_BYTES = 50 * 1024   # 50 KB per file
_MAX_TOTAL_BYTES  = 100 * 1024  # 100 KB total

async def read_txt_attachments(message) -> str:
    """
    Read .txt attachments from a Discord message safely into memory.
    - Whitelist: .txt extension only (case-insensitive)
    - MIME check: content-type must start with text/
    - Size caps: 50 KB/file, 100 KB total
    - Never saved to disk
    """
    if not message.attachments:
        return ''
    parts = []
    total = 0
    async with httpx.AsyncClient(timeout=10) as client:
        for att in message.attachments:
            name = att.filename or ''
            if not name.lower().endswith('.txt'):
                continue
            ct = (att.content_type or '').split(';')[0].strip().lower()
            if ct and not ct.startswith('text/'):
                continue
            size = att.size or 0
            if size > _MAX_ATTACH_BYTES:
                continue
            if total + size > _MAX_TOTAL_BYTES:
                break
            try:
                resp = await client.get(att.url)
                raw = resp.content[:_MAX_ATTACH_BYTES]
                total += len(raw)
                text = raw.decode('utf-8', errors='replace')
                parts.append(f'[attachment: {name}]\n{text}')
            except Exception:
                pass
    return '\n\n'.join(parts)


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

async def check_twitter_token():
    """Background task: check Twitter token health every 24h, DM owner if dead."""
    await bot.wait_until_ready()
    await asyncio.sleep(60)  # wait 1 min after startup before first check
    while not bot.is_closed():
        if TWITTER_AUTH_TOKEN and TWITTER_CT0:
            bearer = "Bearer AAAAAAAAAAAAAAAAAAAAAFXzAwAAAAAAMHCxpeSDG1gLNLghVe8d74hl6k4%3DRUMF4xAQLsbeBhTSRrCiQpJtxoGWeyHrDb5te2jpGskWDFW82F"
            try:
                import json as _json
                async with httpx.AsyncClient(timeout=10) as c:
                    r = await c.get(
                        "https://x.com/i/api/graphql/bshMIjqDk8LTXTq4w91WKw/SearchTimeline",
                        headers={
                            "authorization": bearer,
                            "cookie": f"auth_token={TWITTER_AUTH_TOKEN}; ct0={TWITTER_CT0}",
                            "x-csrf-token": TWITTER_CT0,
                            "x-twitter-auth-type": "OAuth2Session",
                            "x-twitter-active-user": "yes",
                            "origin": "https://x.com",
                            "referer": "https://x.com/search",
                            "user-agent": "Mozilla/5.0",
                        },
                        params={
                            "variables": _json.dumps({"rawQuery": "test", "count": 1, "querySource": "typed_query", "product": "Latest"}),
                            "features": _json.dumps({"responsive_web_graphql_exclude_directive_enabled": True}),
                        },
                    )
                if r.status_code in (401, 403):
                    print(f"[twitter-health] Token dead: HTTP {r.status_code}")
                    if OWNER_DISCORD_ID:
                        try:
                            owner = await bot.fetch_user(OWNER_DISCORD_ID)
                            await owner.send(
                                f"**Twitter token expired** (HTTP {r.status_code})\n"
                                "Update `TWITTER_AUTH_TOKEN` and `TWITTER_CT0` in server `.env`, then `pm2 restart discord-bot`."
                            )
                        except Exception as dm_err:
                            print(f"[twitter-health] Could not DM owner: {dm_err}")
                else:
                    print(f"[twitter-health] Token OK (HTTP {r.status_code})")
            except Exception as e:
                print(f"[twitter-health] Check failed: {e}")
        await asyncio.sleep(CHECK_INTERVAL)


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
    bot.loop.create_task(check_twitter_token())


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
async def on_message_edit(before, after):
    """Re-dispatch edited messages that newly mention the bot."""
    was_mentioned = bot.user in before.mentions
    now_mentioned = bot.user in after.mentions
    if not was_mentioned and now_mentioned:
        await on_message(after)

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
        raw_content = message.content.replace(f'<@{bot.user.id}>', '').replace(f'<@!{bot.user.id}>', '').strip()
        # Resolve all user mentions (<@ID>) to display names so the bot knows who was tagged
        for mentioned_user in message.mentions:
            if mentioned_user.id == bot.user.id:
                continue
            display = mentioned_user.display_name or mentioned_user.name
            raw_content = raw_content.replace(f'<@{mentioned_user.id}>', f'@{display}')
            raw_content = raw_content.replace(f'<@!{mentioned_user.id}>', f'@{display}')
        sender_name = message.author.display_name or message.author.name
        user_input = f'<sender>{sender_name}</sender> {raw_content}' if raw_content else ''
        attachment_text = await read_txt_attachments(message)
        if attachment_text:
            user_input = (user_input + '\n\n' + attachment_text).strip()
        if user_input:
            mention = message.author.mention
            sent = await message.channel.send(f'{mention} ▍', suppress_embeds=True)
            accumulated = ''
            current_status = ''
            loop = asyncio.get_event_loop()
            last_edit = loop.time()
            # max content per edit: 2000 chars total; reserve ~30 for mention + newline
            _LIMIT = 1960

            def _fmt(body: str, suffix: str = '') -> str:
                return f'{mention}\n{body}{suffix}'

            try:
                async with message.channel.typing():
                    async for event in stream_agent_message(message.channel.id, user_input):
                        kind, data = event
                        if kind == 'status':
                            current_status = data
                            base = strip_tables(accumulated)
                            preview = (base[:_LIMIT - 60] + '...') if len(base) > _LIMIT - 60 else base
                            sep = '\n\n' if preview else ''
                            try:
                                await sent.edit(content=_fmt(f'{preview}{sep}_{current_status}_'), suppress=True)
                            except Exception:
                                pass
                        elif kind == 'image_file':
                            try:
                                img_data, img_fname = data
                                await message.channel.send(file=discord.File(io.BytesIO(img_data), filename=img_fname))
                            except Exception as img_err:
                                try:
                                    await message.channel.send(f"Failed to upload image: {img_err}")
                                except Exception:
                                    pass
                        elif kind == 'text':
                            accumulated += data
                            current_status = ''
                            now = loop.time()
                            if now - last_edit >= 1.0 and accumulated.strip():
                                preview = strip_tables(accumulated)
                                display = (preview[:_LIMIT - 3] + '...') if len(preview) > _LIMIT else preview
                                try:
                                    await sent.edit(content=_fmt(display, ' ▍'), suppress=True)
                                except Exception:
                                    pass
                                last_edit = now
            except Exception as e:
                err_str = str(e).lower()
                if '429' in err_str or 'rate' in err_str:
                    await sent.edit(content=_fmt('rate limited rn, try again in a bit'), suppress=True)
                else:
                    await sent.edit(content=_fmt('something went wrong, try again'), suppress=True)
                    print(f'[kuro] unhandled error: {e}', flush=True)
                return

            final = strip_tables(accumulated)
            if not final.strip():
                await sent.edit(content=_fmt('...'), suppress=True)
            elif len(final) <= _LIMIT:
                await sent.edit(content=_fmt(final), suppress=True)
            else:
                chunks = [final[i:i+_LIMIT] for i in range(0, len(final), _LIMIT)]
                await sent.edit(content=_fmt(chunks[0]), suppress=True)
                for chunk in chunks[1:]:
                    await message.channel.send(chunk, suppress_embeds=True)
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
            attachment_text = await read_txt_attachments(message)
            if attachment_text:
                user_input = (user_input + '\n\n' + attachment_text).strip()
            if user_input:
                sent = await message.channel.send('▍', suppress_embeds=True)
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
                                    await sent.edit(content=f'{preview}{sep}_{current_status}_', suppress=True)
                                except Exception:
                                    pass
                            elif kind == 'image_file':
                                try:
                                    img_data, img_fname = data
                                    await message.channel.send(file=discord.File(io.BytesIO(img_data), filename=img_fname))
                                except Exception as img_err:
                                    try:
                                        await message.channel.send(f"Failed to upload image: {img_err}")
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
                                        await sent.edit(content=display + ' ▍', suppress=True)
                                    except Exception:
                                        pass
                                    last_edit = now
                except Exception as e:
                    await sent.edit(content=f'error: {e}', suppress=True)
                    return

                final = strip_tables(accumulated)
                if not final.strip():
                    await sent.edit(content='...', suppress=True)
                elif len(final) <= 1900:
                    await sent.edit(content=final, suppress=True)
                else:
                    chunks = [final[i:i+1900] for i in range(0, len(final), 1900)]
                    await sent.edit(content=chunks[0], suppress=True)
                    for chunk in chunks[1:]:
                        await message.channel.send(chunk, suppress_embeds=True)

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
