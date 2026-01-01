import discord
from discord.ext import commands
from datetime import datetime, timedelta
import io
import aiohttp
import asyncio
import pytz
from PIL import Image
import random
import os
import requests
import base64
import re
from services.to_github import *
from dotenv import load_dotenv

load_dotenv()

def normalize_name(text):
    return re.sub(r'[^a-z0-9]', '', text.lower())

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.dm_messages = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix='>', intents=intents)

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
SPAMMING_CHANNEL_ID = 1250850841385238599
SERVER_ID = 1250679106899673121
CTF_HELPME_CHANNEL_ID = 1251857136804302969
CTF_ANNOUNCE_CHANNEL_ID = 1251192205381472296
CHECK_INTERVAL = 24 * 60 * 60

current_year = datetime.now().year
current_year_short = str(current_year)[-2:]

async def send_anonymous_message(channel_id, formatted_message, dm_channel):
    channel = bot.get_channel(channel_id)
    if channel:
        await channel.send(formatted_message)
        await dm_channel.send(f"Your message has been sent to {channel.name} anonymously.")

async def is_member_of_guild(user):
    guild = bot.get_guild(SERVER_ID)
    return any(member.id == user.id for member in guild.members)

def convert_to_myt(utc_time_str):
    utc_time = datetime.fromisoformat(utc_time_str.replace('Z', '+00:00'))
    return utc_time.astimezone(pytz.timezone('Asia/Kuala_Lumpur')).isoformat()

async def fetch_event_details(event_id):
    url = f'https://ctftime.org/api/v1/events/{event_id}/'
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            return await response.json() if response.status == 200 else None

async def fetch_image(url):
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            return Image.open(io.BytesIO(await response.read())) if response.status == 200 else None

async def create_category_if_not_exists(guild, category_name):
    category = discord.utils.get(guild.categories, name=category_name)
    return category or await guild.create_category(category_name)

async def move_channel_to_archive(channel):
    global current_year
    archive_category = await create_category_if_not_exists(channel.guild, f'archive-{current_year}')
    await channel.edit(category=archive_category)
    print(f"Moved channel {channel.name} to {archive_category.name}")

async def fetch_upcoming_events():
    start = int(datetime.now().timestamp())
    end = int((datetime.now() + timedelta(weeks=2)).timestamp())
    url = f'https://ctftime.org/api/v1/events/?limit=5&start={start}&finish={end}'
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            return await response.json() if response.status == 200 else None

async def check_yearly_update():
    global current_year, current_year_short
    await bot.wait_until_ready()
    while not bot.is_closed():
        now = datetime.now()
        if now.year != current_year:
            guild = bot.get_guild(SERVER_ID)
            if guild:
                current_year = now.year
                current_year_short = str(current_year)[-2:]
                await create_category_if_not_exists(guild, f'ctf-{current_year}')
                await create_category_if_not_exists(guild, f'archive-{current_year}')
                print(f"Year has changed to {current_year}. Categories updated.")
        await asyncio.sleep(CHECK_INTERVAL)

async def handle_anonymous_question(message, channel_name=None):
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
        await send_anonymous_message(channel.id, formatted_message, message.channel)
    else:
        await send_anonymous_message(CTF_HELPME_CHANNEL_ID, formatted_message, message.channel)

async def create_channel_and_event(guild, event):
    category_name = f'ctf-{current_year}'
    channel_name = event['title'].lower().replace(' ', '-')
    category = await create_category_if_not_exists(guild, category_name)
    for channel in category.channels:
        if channel.name == channel_name:
            return None, f"Cannot create CTF '{event['title']}', duplicate event."
    role_name = f"{event['title']} {current_year_short}"
    interested_role = await guild.create_role(
        name=role_name,
        colour=discord.Colour(0x0000FF),
        mentionable=True,
        reason=f"Role for {event['title']} CTF event"
    )
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        interested_role: discord.PermissionOverwrite(view_channel=True, send_messages=True)
        }
    channel = await guild.create_text_channel(channel_name, category=category, overwrites=overwrites)
    start_time_myt, finish_time_myt = convert_to_myt(event['start']), convert_to_myt(event['finish'])
    image = await fetch_image(event['logo']) if event.get('logo') else None
    if image is None:
        image_url = "https://raw.githubusercontent.com/vicevirus/front-end-ctf-sharing-materials/main/ctf_event.png"
        image = await fetch_image(image_url)
    with io.BytesIO() as image_binary:
        image.save(image_binary, format='PNG')
        image_binary.seek(0)
        image_bytes = image_binary.read()
    description = event['description'] if len(event['description']) <= 1000 else event['description'][:997] + '...'
    scheduled_event = await guild.create_scheduled_event(
        name=event['title'],
        start_time=datetime.fromisoformat(start_time_myt),
        end_time=datetime.fromisoformat(finish_time_myt),
        description=description,
        entity_type=discord.EntityType.external,
        privacy_level=discord.PrivacyLevel.guild_only,
        location=event['url'],
        image=image_bytes
    )
    announce_channel = bot.get_channel(CTF_ANNOUNCE_CHANNEL_ID)
    if not announce_channel:
        return None, None, interested_role
    
    ctf_message = await announce_channel.send(
        f"@everyone Successfully created CTF \"{event['title']}\"! React with 👍 if you're playing or want to access the channel."
    )
    await ctf_message.add_reaction("👍")
    return channel, ctf_message, interested_role


@bot.event
async def on_raw_reaction_add(payload):
    if payload.emoji.name == "👍":
        guild = bot.get_guild(payload.guild_id)
        if not guild:
            return
        member = guild.get_member(payload.user_id)
        if not member or member.bot:
            return
        message = await bot.get_channel(payload.channel_id).fetch_message(payload.message_id)
        if message.author.id != bot.user.id:
            return
        event_name = message.content.split('"')[1]
        role_name = f"{event_name} {current_year_short}"
        role = discord.utils.get(guild.roles, name=role_name)
        if role:
            await member.add_roles(role)
            await member.send(f"You have been granted access to the CTF channel for {event_name}.")

async def send_help_message(channel):
    help_message = (
        "**Bot Commands:**\n"
        "```markdown\n"
        ">ctf create <ctftime_event_id>\n"
        "    Create a new CTF channel and schedule an event.\n\n"
        ">ctf archive\n"
        "    Move the current CTF channel to the archive category.\n\n"
        ">ctf upcoming\n"
        "    List upcoming CTF events for the week (shows only the next 5). See ctftime.org for more.\n\n"
        ">ctf writeup\n"
        "    Compile and upload writeups to the REU1N0N GitHub repo.\n"
        ">ask <question/idea>\n"
        "    Send an anonymous question or idea to the general anonymous questions channel.\n\n"
        ">ask ctf <ctfchannel_name> <question/idea>\n"
        "    Send an anonymous question or idea to a specific CTF channel.\n\n"
        ">bot help\n"
        "    Display this help message.\n\n"
        ">bot help writeup\n"
        "    Show details for the '>ctf writeup' command.\n"
        "```"
    )
    await channel.send(help_message)

async def send_writeup_command(channel):
    writeup_message = (
        "**Command:** >ctf writeup\n\n"
        "**What:** Upload all writeups from the current channel to the REU1N0N GitHub repo.\n\n"
        "**When:** Use at the end of a CTF or when all writeups are ready.\n\n"
        "**Format:** We accept markdown right after `Category` and `Challenge Name`. Here's a minimal example:\n"
        "```\n"
        "---\n"
        "Category: crypto\n"
        "Challenge Name: baby-rsa\n"
        "\n"
        "# Heading 1\n"
        "### Heading 2\n"
        "Regular text, `inline code`, and lists are supported.\n"
        "- item 1\n"
        "- item 2\n"
        "\n"
        "---\n"
        "```\n"
    )
    await channel.send(writeup_message)

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')
    guild = bot.get_guild(SERVER_ID)
    if guild:
        await create_category_if_not_exists(guild, f'ctf-{current_year}')
        await create_category_if_not_exists(guild, f'archive-{current_year}')
    bot.loop.create_task(check_yearly_update())

@bot.event
async def on_message(message):
    # This part is for processing messages via DM
    if isinstance(message.channel, discord.DMChannel) and message.author != bot.user:
        if await is_member_of_guild(message.author):
            if message.content.startswith('>ask ctf '):
                parts = message.content.split(' ')
                if len(parts) > 3:
                    await handle_anonymous_question(message, parts[2])
                else:
                    await message.channel.send("Usage: >ask ctf <channel_name> <question>")
            elif message.content.startswith('>ask '):
                await handle_anonymous_question(message)
            elif message.content.startswith('>bot help'):
                parts = message.content.split()
                if len(parts) > 2:
                    if parts[2] == 'writeup':
                        await send_writeup_command(message.channel)
                    else:
                        await send_help_message(message.channel)
                else:
                    await send_help_message(message.channel)
        else:
            await message.channel.send("You must be a member of the server to use this command.")
    # This part is for processing messages via Channel
    if message.content.startswith('>ctf create ') and message.channel.id == SPAMMING_CHANNEL_ID:
        event_id = message.content[len('>ctf create '):].strip()
        event = await fetch_event_details(event_id)
        if event:
            new_channel, ctf_message, interested_role = await create_channel_and_event(message.guild, event)
        else:
            await message.channel.send("Failed to fetch event data. Please check the event ID.")

    elif message.content.startswith('>ctf archive'):
        if message.channel.category and message.channel.category.name == f'ctf-{current_year}':
            if message.author.guild_permissions.administrator:
                await move_channel_to_archive(message.channel)
                await message.channel.send(f"Channel '{message.channel.name}' has been moved to the archive.")
            else:
                await message.channel.send("You do not have permission to archive channels.")
        else:
            await message.channel.send("This command can only be used in channels within the current year's CTF category.")

    elif message.content.startswith('>ctf upcoming'):
        events = await fetch_upcoming_events()
        seen_event_ids = set()
        if events:
            embed = discord.Embed(title="Upcoming CTF Events for the Week", color=random.randint(0, 0xFFFFFF))
            for event in events:
                if event['id'] in seen_event_ids:
                    continue
                seen_event_ids.add(event['id'])
                start_time = convert_to_myt(event['start'])
                end_time = convert_to_myt(event['finish'])
                start_time_formatted = datetime.fromisoformat(start_time).strftime('%Y-%m-%d %H:%M:%S MYT')
                end_time_formatted = datetime.fromisoformat(end_time).strftime('%Y-%m-%d %H:%M:%S MYT')
                duration = f"{event['duration']['days']}d {event['duration']['hours']}h"
                event_embed = discord.Embed(
                    title=event['title'],
                    description=(
                        f"**Event ID:** {event['id']}\n"
                        f"**Weight:** {event['weight']}\n"
                        f"**Duration:** {duration}\n"
                        f"**Start Time:** {start_time_formatted}\n"
                        f"**End Time:** {end_time_formatted}\n"
                        f"**Format:** {event['format']}\n"
                        f"**[More Info]({event['url']})**"
                    ),
                    color=random.randint(0, 0xFFFFFF)
                )
                if event['logo']:
                    event_embed.set_thumbnail(url=event['logo'])
                await message.channel.send(embed=event_embed)
            embed.set_footer(text="Showing only 5 upcoming CTF events. For more, check ctftime.org.")
        else:
            await message.channel.send("No upcoming CTF events found.")

    elif message.content.startswith(">ctf writeup"):
        try:
            cat_name = message.channel.category.name if message.channel.category else ""
            if not (cat_name.startswith("ctf-") or cat_name.startswith("archive-")):
                await message.channel.send("This command can only be used in a CTF channel.")
                return
            ctf = message.channel.name
            messages = [msg async for msg in message.channel.history(limit=10000)]
            writeup_messages = [msg for msg in messages if msg.content.startswith("---") and msg.content.endswith("---")]
            if not writeup_messages:
                await message.channel.send("No writeup found.")
                return
            for writeup_msg in writeup_messages:
                try:
                    lines = writeup_msg.content.strip().split("\n")
                    if len(lines) < 4 or not lines[0].startswith("---") or not lines[-1].endswith("---"):
                        continue
                    category = None
                    challenge_name = None
                    content_start_index = None
                    for i, line in enumerate(lines[1:-1]):
                        if line.startswith("Category:"):
                            category = line.split("Category:")[1].strip()
                        elif line.startswith("Challenge Name:"):
                            challenge_name = line.split("Challenge Name:")[1].strip()
                        elif line.strip() == "":
                            content_start_index = i + 2
                            break
                    if not category or not challenge_name or content_start_index is None:
                        await message.channel.send(f"{writeup_msg.author.mention} Missing required fields (Category or Challenge Name) in message: https://discord.com/channels/{message.guild.id}/{message.channel.id}/{writeup_msg.id}")
                        continue
                    category = normalize_name(category)
                    challenge_name = normalize_name(challenge_name)
                    content = "\n".join(lines[content_start_index:-1])
                    sender_username = writeup_msg.author.name
                    a = create_folder_structure(ctf, category, challenge_name, content, sender_username)
                    if a == "exist":
                        await message.channel.send(f"`CTF-writeups/{datetime.now().year}/{ctf}/{category}-{challenge_name}.md` already exists. Skipping...")
                    elif a == "updated":
                        await message.channel.send(f"Updating `CTF-writeups/{datetime.now().year}/{ctf}/{category}-{challenge_name}.md`...")
                    elif a == "created":
                        await message.channel.send(f"Creating `CTF-writeups/{datetime.now().year}/{ctf}/{category}-{challenge_name}.md`...")
                except Exception as e:
                    await message.channel.send(f"{writeup_msg.author.mention} Error processing your writeup in message: https://discord.com/channels/{message.guild.id}/{message.channel.id}/{writeup_msg.id} - {str(e)}")
                    print(f"Error processing writeup message: {str(e)}")
            await message.channel.send("All previous writeup have been processed.")
        except Exception as e:
            await message.channel.send(f"Failed to process the request: {str(e)}")

    elif message.content.startswith('>bot help'):
        parts = message.content.split()
        if len(parts) > 2:
            if parts[2] == 'writeup':
                await send_writeup_command(message.channel)
            else:
                await send_help_message(message.channel)
        else:
            await send_help_message(message.channel)

bot.run(TOKEN)
