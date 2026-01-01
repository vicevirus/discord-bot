"""
Writeup handlers: quick submit, batch upload, and delete.
"""

import os
import aiohttp
import discord
from datetime import datetime

from config import CATEGORY_PATTERNS, CHALLENGE_PATTERNS
from utils import normalize_name, is_ctf_channel
from services.github import (
    create_folder_structure,
    upload_binary_to_github,
    get_writeup_author,
    delete_writeup,
)


def get_ctf_name(channel):
    """Get CTF name from channel or thread's parent."""
    if isinstance(channel, discord.Thread):
        return channel.parent.name
    return channel.name


# =============================================================================
# BATCH WRITEUP PARSING
# =============================================================================

def parse_writeup_metadata(lines):
    """
    Parse category and challenge name from writeup lines using fuzzy matching.
    
    Returns: (category, challenge_name, content_start_index, errors)
    """
    category = None
    challenge_name = None
    content_start_index = None
    errors = []
    
    for i, line in enumerate(lines[1:-1]):  # Skip first and last ---
        line_lower = line.lower().strip()
        
        # Try to match category
        if category is None:
            for pattern in CATEGORY_PATTERNS:
                if line_lower.startswith(pattern):
                    category = line.split(":", 1)[1].strip()
                    break
        
        # Try to match challenge name
        if challenge_name is None:
            for pattern in CHALLENGE_PATTERNS:
                if line_lower.startswith(pattern):
                    challenge_name = line.split(":", 1)[1].strip()
                    break
        
        # Find content start (first blank line after headers)
        if line.strip() == "" and content_start_index is None and (category or challenge_name):
            content_start_index = i + 2
            break
    
    # Build helpful error messages
    if not category:
        errors.append("❓ Missing **Category** (try: `Category: crypto`)")
    if not challenge_name:
        errors.append("❓ Missing **Challenge Name** (try: `Challenge Name: baby-rsa`)")
    if content_start_index is None and category and challenge_name:
        errors.append("❓ Missing **blank line** after headers before content")
    
    return category, challenge_name, content_start_index, errors


async def process_batch_writeup(message, writeup_msg, ctf):
    """
    Process a single writeup message in batch mode.
    
    Returns: (success: bool, status: str)
    """
    msg_link = f"https://discord.com/channels/{message.guild.id}/{message.channel.id}/{writeup_msg.id}"
    content_raw = writeup_msg.content.strip()
    lines = content_raw.split("\n")
    
    # Validate basic format
    if len(lines) < 4:
        await message.channel.send(
            f"⚠️ {writeup_msg.author.mention} Writeup too short (need at least 4 lines): {msg_link}"
        )
        return False, "too_short"
    
    if not lines[0].strip().startswith("---"):
        return False, "not_writeup"  # Skip silently
    
    # Check closing ---
    if not lines[-1].strip().endswith("---"):
        await message.channel.send(
            f"⚠️ {writeup_msg.author.mention} Missing closing `---` at end: {msg_link}"
        )
        return False, "no_closing"
    
    # Parse metadata with fuzzy matching
    category, challenge_name, content_start_index, errors = parse_writeup_metadata(lines)
    
    if errors:
        error_text = "\n".join(errors)
        await message.channel.send(
            f"⚠️ {writeup_msg.author.mention} Issues found:\n{error_text}\n🔗 {msg_link}"
        )
        return False, "parse_error"
    
    # Normalize names
    category = normalize_name(category)
    challenge_name = normalize_name(challenge_name)
    
    # Extract content
    content = "\n".join(lines[content_start_index:-1])
    
    if not content.strip():
        await message.channel.send(
            f"⚠️ {writeup_msg.author.mention} Writeup has no content: {msg_link}"
        )
        return False, "no_content"
    
    # Upload to GitHub
    sender_username = writeup_msg.author.name
    result = create_folder_structure(ctf, category, challenge_name, content, sender_username)
    
    if result == "exist":
        await message.channel.send(f"⏭️ `{category}-{challenge_name}.md` already exists. Skipping...")
        return False, "exists"
    elif result == "updated":
        await message.channel.send(f"📝 Updated `{category}-{challenge_name}.md`")
        return True, "updated"
    elif result == "created":
        await message.channel.send(f"✅ Created `{category}-{challenge_name}.md`")
        return True, "created"
    
    return False, "unknown"


async def handle_batch_writeup(message):
    """Handle the >ctf writeup batch command."""
    if not is_ctf_channel(message.channel):
        await message.channel.send("❌ This command can only be used in a CTF channel.")
        return
    
    ctf = get_ctf_name(message.channel)
    await message.channel.send("🔍 Scanning channel for writeups...")
    
    # Fetch channel history
    messages = [msg async for msg in message.channel.history(limit=10000)]
    writeup_messages = [msg for msg in messages if msg.content.strip().startswith("---")]
    
    if not writeup_messages:
        await message.channel.send("❌ No writeup found. Writeups should start with `---`")
        return
    
    # Process each writeup
    processed = 0
    skipped = 0
    
    for writeup_msg in writeup_messages:
        try:
            success, status = await process_batch_writeup(message, writeup_msg, ctf)
            if success:
                processed += 1
            elif status != "not_writeup":
                skipped += 1
        except Exception as e:
            msg_link = f"https://discord.com/channels/{message.guild.id}/{message.channel.id}/{writeup_msg.id}"
            await message.channel.send(f"❌ {writeup_msg.author.mention} Error: {str(e)}\n🔗 {msg_link}")
            print(f"Error processing writeup message: {str(e)}")
            skipped += 1
    
    await message.channel.send(f"📊 **Done!** Processed: {processed} | Skipped: {skipped}")


# =============================================================================
# QUICK WRITEUP
# =============================================================================

# Max file size: 50MB (GitHub limit is 100MB, we use safe margin)
MAX_ATTACHMENT_SIZE = 50 * 1024 * 1024

async def upload_attachments_to_github(attachments, ctf, challenge_name):
    """
    Download attachments and upload to GitHub.
    
    Returns: Markdown string with attachment links.
    """
    if not attachments:
        return ""
    
    attachment_section = "\n\n## Attachments\n"
    year = datetime.now().year
    timeout = aiohttp.ClientTimeout(total=60)  # 60s for large files
    
    for attachment in attachments:
        try:
            # Check file size before downloading
            if attachment.size and attachment.size > MAX_ATTACHMENT_SIZE:
                attachment_section += f"\n- ⚠️ [{attachment.filename}]({attachment.url}) (too large for GitHub, Discord link)\n"
                continue
            
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(attachment.url) as resp:
                    if resp.status != 200:
                        attachment_section += f"\n- [{attachment.filename}]({attachment.url})\n"
                        continue
                    
                    file_data = await resp.read()
            
            # Create path for attachment in GitHub
            attachment_path = (
                f"{os.getenv('PARENT_FOLDER')}/{year}/{ctf}/assets/"
                f"{normalize_name(challenge_name)}-{attachment.filename}"
            )
            
            # Upload to GitHub
            github_url = upload_binary_to_github(attachment_path, file_data)
            
            if github_url:
                # Render images inline, other files as links
                if attachment.content_type and attachment.content_type.startswith('image/'):
                    attachment_section += f"\n![{attachment.filename}]({github_url})\n"
                else:
                    attachment_section += f"\n- [{attachment.filename}]({github_url})\n"
            else:
                # Fallback to Discord CDN
                attachment_section += f"\n- [{attachment.filename}]({attachment.url})\n"
                
        except Exception as e:
            print(f"Error uploading attachment {attachment.filename}: {e}")
            attachment_section += f"\n- [{attachment.filename}]({attachment.url})\n"
    
    return attachment_section


async def handle_quick_writeup(message):
    """Handle the >writeup cat:X title:Y command."""
    if not is_ctf_channel(message.channel):
        await message.channel.send("❌ This command can only be used in a CTF channel.")
        return
    
    ctf = get_ctf_name(message.channel)
    full_text = message.content
    from_message_txt = False
    
    # Separate message.txt from other attachments
    message_txt_attachment = None
    other_attachments = []
    
    for attachment in message.attachments:
        if attachment.filename == 'message.txt' and not message.content.strip():
            message_txt_attachment = attachment
            from_message_txt = True
        else:
            other_attachments.append(attachment)
    
    # Download message.txt if present (Discord auto-converts long messages)
    if message_txt_attachment:
        async with aiohttp.ClientSession() as session:
            async with session.get(message_txt_attachment.url) as resp:
                if resp.status == 200:
                    full_text = await resp.text()
    
    if not full_text.strip():
        await message.channel.send("❌ No content found.")
        return
    
    lines = full_text.split('\n')
    first_line = lines[0]
    
    # Validate command format
    if not first_line.strip().startswith('>writeup '):
        return
    
    # Parse cat: and title: from first line
    category = None
    challenge_name = None
    
    parts = first_line.split()
    for part in parts[1:]:  # Skip '>writeup'
        part_lower = part.lower()
        if part_lower.startswith('cat:'):
            category = part[4:].strip()
        elif part_lower.startswith('title:'):
            challenge_name = part[6:].strip()
    
    if not category or not challenge_name:
        await message.channel.send(
            "❌ Usage: `>writeup cat:<category> title:<challenge-name>`\n"
            "Example: `>writeup cat:crypto title:baby-rsa`"
        )
        return
    
    # Validate category and title are not empty after stripping
    if not category.strip() or not challenge_name.strip():
        await message.channel.send(
            "❌ Category and title cannot be empty!\n"
            "Example: `>writeup cat:crypto title:baby-rsa`"
        )
        return
    
    # Content is everything after the first line
    content = '\n'.join(lines[1:]).strip() if len(lines) > 1 else ""
    
    if not content and not other_attachments:
        await message.channel.send("❌ No content provided. Add your writeup after the command or attach files.")
        return
    
    # Upload attachments to GitHub
    attachment_section = await upload_attachments_to_github(other_attachments, ctf, challenge_name)
    
    # Build final content
    header = f"# {category} - {challenge_name}\n\n"
    full_content = header + content + attachment_section
    
    # Normalize names for file path
    category_normalized = normalize_name(category)
    challenge_normalized = normalize_name(challenge_name)
    sender_username = message.author.name
    
    # Upload to GitHub
    result = create_folder_structure(ctf, category_normalized, challenge_normalized, full_content, sender_username)
    
    # Build GitHub URL
    year = datetime.now().year
    github_url = (
        f"https://github.com/{os.getenv('GITHUB_REPO_OWNER')}/{os.getenv('GITHUB_REPO_NAME')}"
        f"/blob/main/{os.getenv('PARENT_FOLDER')}/{year}/{ctf}/{category_normalized}-{challenge_normalized}.md"
    )
    
    long_msg = " (long content auto-parsed from message.txt)" if from_message_txt else ""
    
    if result == "exist":
        await message.channel.send(f"⏭️ Writeup already exists (identical content): {github_url}")
    elif result == "updated":
        await message.channel.send(f"📝 Writeup updated{long_msg}: {github_url}")
    elif result == "created":
        await message.channel.send(f"✅ Writeup created{long_msg}: {github_url}")


# =============================================================================
# WRITEUP DELETE
# =============================================================================

async def handle_writeup_delete(message):
    """Handle the >writeup-delete command."""
    if not is_ctf_channel(message.channel):
        await message.channel.send("❌ This command can only be used in a CTF channel.")
        return
    
    ctf = get_ctf_name(message.channel)
    parts = message.content.split()
    
    # Parse cat: and title:
    category = None
    challenge_name = None
    
    for part in parts[1:]:
        part_lower = part.lower()
        if part_lower.startswith('cat:'):
            category = part[4:].strip()
        elif part_lower.startswith('title:'):
            challenge_name = part[6:].strip()
    
    if not category or not challenge_name:
        await message.channel.send("❌ Usage: `>writeup-delete cat:<category> title:<challenge-name>`")
        return
    
    category_normalized = normalize_name(category)
    challenge_normalized = normalize_name(challenge_name)
    
    # Check if user is author or admin
    is_admin = message.author.guild_permissions.administrator
    author = get_writeup_author(ctf, category_normalized, challenge_normalized)
    
    if author is None:
        await message.channel.send(f"❌ Writeup not found: `{category_normalized}-{challenge_normalized}.md`")
        return
    
    is_author = (author.lower() == message.author.name.lower())
    
    if not is_admin and not is_author:
        await message.channel.send(f"❌ Only the author ({author}) or admins can delete this writeup.")
        return
    
    # Delete from GitHub
    result = delete_writeup(ctf, category_normalized, challenge_normalized)
    
    if result == "deleted":
        await message.channel.send(f"🗑️ Writeup deleted: `{category_normalized}-{challenge_normalized}.md`")
    elif result == "not_found":
        await message.channel.send(f"❌ Writeup not found: `{category_normalized}-{challenge_normalized}.md`")
    else:
        await message.channel.send("❌ Failed to delete writeup.")
