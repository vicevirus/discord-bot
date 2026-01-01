"""
Help message constants and functions.
"""


# =============================================================================
# HELP MESSAGES
# =============================================================================

HELP_MESSAGE = """**Bot Commands:**
```markdown
>ctf create <ctftime_event_id>
    Create a new CTF channel and schedule an event.

>ctf archive
    Move the current CTF channel to the archive category.

>ctf upcoming
    List upcoming CTF events (next 5). See ctftime.org for more.

>writeup cat:<category> title:<challenge-name>
    Quick writeup submission (supports attachments + long writeups).

>ctf writeup
    Batch compile all writeups from channel (text only).

>writeup-delete cat:<category> title:<challenge-name>
    Delete a writeup from this CTF.

>ask <question/idea>
    Send an anonymous question to the general channel.

>ask ctf <channel> <question>
    Send an anonymous question to a specific CTF channel.

>bot help
    Display this help message.

>bot help writeup
    Show details for writeup commands.
```"""


WRITEUP_HELP_MESSAGE = """**📝 Writeup Commands**

**Method 1: Quick Submit (Recommended)**
```
>writeup cat:crypto title:baby-rsa
Your writeup content here...

Code blocks, markdown, everything works!
Attach images/files to the same message.
```
✅ Images & files auto-uploaded to GitHub (permanent links)

**Method 2: Batch Upload (Text Only)**
Post writeups anywhere in channel:
```
---
Category: crypto
Challenge Name: baby-rsa

Your writeup content...
---
```
Then run `>ctf writeup` to batch upload all.
⚠️ No image/attachment support - use Method 1 for images!

**Delete Writeup**
```
>writeup-delete cat:crypto title:baby-rsa
```
Only author or admin can delete.

💡 Long writeups? No problem - bot auto-handles Discord's message.txt conversion."""


SLASH_HELP_MESSAGE = """**Bot Commands:**
```markdown
>ctf create <ctftime_event_id>
    Create a new CTF channel and schedule an event.

>ctf archive
    Move the current CTF channel to the archive category.

>ctf upcoming
    List upcoming CTF events (next 5). See ctftime.org for more.

>writeup cat:<category> title:<challenge-name>
    Quick writeup submission (supports images/attachments).

>ctf writeup
    Batch upload all writeups from channel (text only).

>writeup-delete cat:<category> title:<challenge-name>
    Delete a writeup from this CTF.

>ask <question/idea>
    Send anonymous question to general channel.

>ask ctf <channel> <question>
    Send anonymous question to specific CTF channel.
```
💡 Use `/help-writeup` for detailed writeup usage."""


SLASH_WRITEUP_HELP_MESSAGE = """**📝 Writeup Commands**

**Method 1: Quick Submit (Recommended)**
```
>writeup cat:crypto title:baby-rsa
Your writeup content here...

Markdown, code blocks - all work!
Paste images directly (ctrl+v).
```
✅ Images & files auto-uploaded to GitHub (permanent)

**Method 2: Batch Upload (Text Only)**
Post writeups anywhere in channel:
```
---
Category: crypto
Challenge Name: baby-rsa

Your writeup content...
---
```
Then run `>ctf writeup` to batch upload all.
⚠️ No image/attachment support - use Method 1 for images!

**Delete Writeup**
```
>writeup-delete cat:crypto title:baby-rsa
```
Only author or admin can delete."""


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

async def send_help_message(channel):
    """Send the main help message."""
    await channel.send(HELP_MESSAGE)


async def send_writeup_help(channel):
    """Send the writeup-specific help message."""
    await channel.send(WRITEUP_HELP_MESSAGE)
