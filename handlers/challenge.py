"""
Challenge tracking via threads within CTF channels.
"""

import discord
import json
import os
from datetime import datetime
from pathlib import Path

# Data storage - relative to project root
DATA_DIR = Path(__file__).parent.parent / "data"
CHALLENGES_FILE = DATA_DIR / "challenges.json"


def is_active_ctf(channel):
    """Check if channel is in an ACTIVE CTF category (not archive)."""
    if isinstance(channel, discord.Thread):
        channel = channel.parent
    if not channel or not channel.category:
        return False
    return channel.category.name.startswith("ctf-")


def ensure_data_dir():
    """Ensure data directory exists."""
    DATA_DIR.mkdir(exist_ok=True)
    if not CHALLENGES_FILE.exists():
        CHALLENGES_FILE.write_text("{}")


def load_challenges():
    """Load challenges from JSON file."""
    ensure_data_dir()
    try:
        return json.loads(CHALLENGES_FILE.read_text())
    except (json.JSONDecodeError, FileNotFoundError):
        return {}


def save_challenges(data):
    """Save challenges to JSON file."""
    ensure_data_dir()
    CHALLENGES_FILE.write_text(json.dumps(data, indent=2))


def get_status_emoji(status):
    """Get status indicator."""
    return {
        "unsolved": "[ ]",
        "working": "[~]", 
        "solved": "[x]"
    }.get(status, "[ ]")


# =============================================================================
# SLASH COMMAND HANDLERS (primary)
# =============================================================================

async def create_challenge_thread(interaction: discord.Interaction, category: str, name: str):
    """
    Create a new challenge thread.
    /chall <category> <name>
    """
    channel = interaction.channel
    
    # Check if in active CTF channel
    if not is_active_ctf(channel):
        await interaction.response.send_message(
            "This command only works in active CTF channels", 
            ephemeral=True
        )
        return
    
    category = category.lower().strip()
    name = name.strip()
    
    if not name:
        await interaction.response.send_message(
            "Challenge name cannot be empty", 
            ephemeral=True
        )
        return
    
    # Create thread with format: [category] challenge name
    thread_name = f"[{category}] {name}"
    
    try:
        thread = await channel.create_thread(
            name=thread_name[:100],  # Discord limit
            type=discord.ChannelType.public_thread,
            reason=f"Challenge created by {interaction.user.name}"
        )
        
        # Store in JSON
        challenges = load_challenges()
        channel_id = str(channel.id)
        
        if channel_id not in challenges:
            challenges[channel_id] = {}
        
        challenges[channel_id][str(thread.id)] = {
            "name": name,
            "category": category,
            "status": "unsolved",
            "created_by": str(interaction.user.id),
            "created_at": datetime.now().isoformat(),
            "solvers": [],
            "working": []
        }
        
        save_challenges(challenges)
        
        # Send initial message in thread
        await thread.send(
            f"**{name}** | `{category}`\n"
            f"Created by {interaction.user.mention}\n\n"
            f"Use `/solved` when done"
        )
        
        await interaction.response.send_message(
            f"Created: {thread.mention}"
        )
        
    except discord.Forbidden:
        await interaction.response.send_message(
            "I don't have permission to create threads", 
            ephemeral=True
        )
    except Exception as e:
        await interaction.response.send_message(
            f"Failed to create thread: {str(e)}", 
            ephemeral=True
        )


async def mark_solved(interaction: discord.Interaction):
    """
    Mark a challenge as solved.
    /solved (run inside a challenge thread)
    """
    channel = interaction.channel
    
    # Must be in a thread
    if not isinstance(channel, discord.Thread):
        await interaction.response.send_message(
            "Use this inside a challenge thread", 
            ephemeral=True
        )
        return
    
    thread = channel
    parent_channel = thread.parent
    
    if not parent_channel or not is_active_ctf(parent_channel):
        await interaction.response.send_message(
            "This thread is not in a CTF channel", 
            ephemeral=True
        )
        return
    
    challenges = load_challenges()
    channel_id = str(parent_channel.id)
    thread_id = str(thread.id)
    
    if channel_id not in challenges or thread_id not in challenges[channel_id]:
        await interaction.response.send_message(
            "This thread is not tracked as a challenge", 
            ephemeral=True
        )
        return
    
    chall = challenges[channel_id][thread_id]
    
    # Check if user already solved
    user_id = str(interaction.user.id)
    if any(s["user_id"] == user_id for s in chall.get("solvers", [])):
        await interaction.response.send_message(
            "You already solved this one",
            ephemeral=True
        )
        return
    
    # Calculate solve time
    created = datetime.fromisoformat(chall["created_at"])
    solved = datetime.now()
    delta = solved - created
    hours, remainder = divmod(int(delta.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)
    
    if hours > 0:
        time_str = f"{hours}h {minutes}m"
    elif minutes > 0:
        time_str = f"{minutes}m {seconds}s"
    else:
        time_str = f"{seconds}s"
    
    # Add solver
    if "solvers" not in chall:
        chall["solvers"] = []
    
    chall["solvers"].append({
        "user_id": user_id,
        "solved_at": solved.isoformat(),
        "time_str": time_str
    })
    
    chall["status"] = "solved"
    save_challenges(challenges)
    
    # Update thread name on first solve
    if len(chall["solvers"]) == 1:
        old_name = thread.name.replace("[SOLVED]", "").strip()
        new_name = f"{old_name} [SOLVED]"
        try:
            await thread.edit(name=new_name[:100])
        except:
            pass
    
    solver_count = len(chall["solvers"])
    if solver_count == 1:
        solve_msg = f"**SOLVED** by {interaction.user.mention} in {time_str}"
    else:
        solve_msg = f"**SOLVED** by {interaction.user.mention} in {time_str} (solver #{solver_count})"
    
    await interaction.response.send_message(solve_msg)
    
    # Announce in parent channel
    await parent_channel.send(
        f"**{chall['name']}** [{chall['category']}] solved by {interaction.user.mention} ({time_str})"
    )


async def mark_working(interaction: discord.Interaction):
    """
    Mark yourself as working on a challenge.
    /working (run inside a challenge thread)
    """
    channel = interaction.channel
    
    if not isinstance(channel, discord.Thread):
        await interaction.response.send_message(
            "Use this inside a challenge thread", 
            ephemeral=True
        )
        return
    
    thread = channel
    parent_channel = thread.parent
    
    if not parent_channel or not is_active_ctf(parent_channel):
        await interaction.response.send_message(
            "This thread is not in a CTF channel", 
            ephemeral=True
        )
        return
    
    challenges = load_challenges()
    channel_id = str(parent_channel.id)
    thread_id = str(thread.id)
    
    if channel_id not in challenges or thread_id not in challenges[channel_id]:
        await interaction.response.send_message(
            "This thread is not tracked as a challenge", 
            ephemeral=True
        )
        return
    
    chall = challenges[channel_id][thread_id]
    
    # Add user to working list
    user_id = str(interaction.user.id)
    if user_id not in chall["working"]:
        chall["working"].append(user_id)
    
    # Update status if unsolved
    if chall["status"] == "unsolved":
        chall["status"] = "working"
    
    save_challenges(challenges)
    
    await interaction.response.send_message(
        f"{interaction.user.mention} is working on this"
    )


async def mark_unsolved(interaction: discord.Interaction):
    """
    Mark a challenge back to unsolved.
    /unsolved (run inside a challenge thread)
    """
    channel = interaction.channel
    
    if not isinstance(channel, discord.Thread):
        await interaction.response.send_message(
            "Use this inside a challenge thread", 
            ephemeral=True
        )
        return
    
    thread = channel
    parent_channel = thread.parent
    
    if not parent_channel or not is_active_ctf(parent_channel):
        await interaction.response.send_message(
            "This thread is not in a CTF channel", 
            ephemeral=True
        )
        return
    
    challenges = load_challenges()
    channel_id = str(parent_channel.id)
    thread_id = str(thread.id)
    
    if channel_id not in challenges or thread_id not in challenges[channel_id]:
        await interaction.response.send_message(
            "This thread is not tracked as a challenge", 
            ephemeral=True
        )
        return
    
    chall = challenges[channel_id][thread_id]
    
    # Reset status
    chall["status"] = "unsolved"
    chall["solvers"] = []
    chall["working"] = []
    
    save_challenges(challenges)
    
    # Update thread name - remove [SOLVED]
    old_name = thread.name.replace("[SOLVED]", "").strip()
    
    try:
        await thread.edit(name=old_name[:100])
    except:
        pass
    
    await interaction.response.send_message("Challenge reset to unsolved")


async def show_status(interaction: discord.Interaction):
    """
    Show status of all challenges in the CTF.
    /status (run in CTF channel or thread)
    """
    channel = interaction.channel
    
    # If in thread, get parent channel
    if isinstance(channel, discord.Thread):
        channel = channel.parent
    
    if not channel or not is_active_ctf(channel):
        await interaction.response.send_message(
            "Use this in a CTF channel", 
            ephemeral=True
        )
        return
    
    challenges = load_challenges()
    channel_id = str(channel.id)
    
    if channel_id not in challenges or not challenges[channel_id]:
        await interaction.response.send_message(
            "No challenges tracked yet. Use `/chall <category> <name>` to create one.",
            ephemeral=True
        )
        return
    
    challs = challenges[channel_id]
    
    # Group by category
    by_category = {}
    for thread_id, chall in challs.items():
        cat = chall["category"]
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append((thread_id, chall))
    
    # Build status message
    lines = ["**Challenge Status**\n"]
    
    total_solved = 0
    total_challs = len(challs)
    
    for category in sorted(by_category.keys()):
        cat_challs = by_category[category]
        solved_in_cat = sum(1 for _, c in cat_challs if c["status"] == "solved")
        
        lines.append(f"**[{category.upper()}]** ({solved_in_cat}/{len(cat_challs)})")
        
        for thread_id, chall in cat_challs:
            status = get_status_emoji(chall["status"])
            name = chall["name"]
            
            # Try to get thread mention
            try:
                thread = channel.get_thread(int(thread_id))
                if thread:
                    name = thread.mention
            except:
                pass
            
            extra = ""
            solvers = chall.get("solvers", [])
            if chall["status"] == "solved" and solvers:
                solver_strs = [f"<@{s['user_id']}> ({s['time_str']})" for s in solvers[:3]]
                if len(solvers) > 3:
                    solver_strs.append(f"+{len(solvers) - 3} more")
                extra = f" - {', '.join(solver_strs)}"
            elif chall["status"] == "working" and chall["working"]:
                workers = ", ".join(f"<@{uid}>" for uid in chall["working"][:3])
                if len(chall["working"]) > 3:
                    workers += f" +{len(chall['working']) - 3}"
                extra = f" - {workers}"
            
            lines.append(f"  {status} {name}{extra}")
            
            if chall["status"] == "solved":
                total_solved += 1
        
        lines.append("")  # Blank line between categories
    
    # Summary at top
    lines.insert(1, f"**Progress: {total_solved}/{total_challs}** challenges solved\n")
    
    await interaction.response.send_message("\n".join(lines), ephemeral=True)


async def delete_challenge(interaction: discord.Interaction):
    """
    Delete a challenge thread.
    Only the creator or admins can delete.
    """
    # Must be in a thread
    if not isinstance(interaction.channel, discord.Thread):
        await interaction.response.send_message("This command only works inside a challenge thread!", ephemeral=True)
        return
    
    thread = interaction.channel
    parent_channel = thread.parent
    
    if not parent_channel or not is_active_ctf(parent_channel):
        await interaction.response.send_message("This thread is not in a CTF channel!", ephemeral=True)
        return
    
    challenges = load_challenges()
    channel_id = str(parent_channel.id)
    thread_id = str(thread.id)
    
    if channel_id not in challenges or thread_id not in challenges[channel_id]:
        await interaction.response.send_message("This thread is not tracked as a challenge!", ephemeral=True)
        return
    
    chall = challenges[channel_id][thread_id]
    
    # Check permission: creator or admin
    is_creator = str(interaction.user.id) == chall["created_by"]
    is_admin = interaction.user.guild_permissions.administrator
    
    if not is_creator and not is_admin:
        await interaction.response.send_message("Only the creator or admins can delete challenges!", ephemeral=True)
        return
    
    # Remove from JSON
    del challenges[channel_id][thread_id]
    if not challenges[channel_id]:
        del challenges[channel_id]
    save_challenges(challenges)
    
    # Delete the thread
    try:
        await interaction.response.send_message(f"Deleting challenge: **{chall['name']}**")
        await thread.delete(reason=f"Deleted by {interaction.user.name}")
    except discord.Forbidden:
        await interaction.response.send_message("I don't have permission to delete this thread!", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"Error deleting thread: {str(e)}", ephemeral=True)


async def auto_track_worker(message):
    """
    Automatically track users who chat in challenge threads as working on them.
    Called from on_message event.
    """
    # Only track in threads
    if not isinstance(message.channel, discord.Thread):
        return
    
    thread = message.channel
    parent_channel = thread.parent
    
    if not parent_channel or not is_active_ctf(parent_channel):
        return
    
    challenges = load_challenges()
    channel_id = str(parent_channel.id)
    thread_id = str(thread.id)
    
    if channel_id not in challenges or thread_id not in challenges[channel_id]:
        return
    
    chall = challenges[channel_id][thread_id]
    
    # Add user to working list if not already there
    user_id = str(message.author.id)
    if user_id not in chall["working"]:
        chall["working"].append(user_id)
        
        # Update status if unsolved
        if chall["status"] == "unsolved":
            chall["status"] = "working"
        
        save_challenges(challenges)


# =============================================================================
# LEGACY PREFIX COMMANDS (keeping for backwards compat)
# =============================================================================

async def handle_chall_create(message):
    """
    Create a new challenge thread.
    Usage: >chall <category> <challenge name>
    Example: >chall web JWT Confused
    """
    if not is_active_ctf(message.channel):
        await message.channel.send("This command only works in CTF channels!")
        return
    
    # Parse: >chall <category> <name>
    content = message.content[len(">chall "):].strip()
    parts = content.split(" ", 1)
    
    if len(parts) < 2:
        await message.channel.send("Usage: `>chall <category> <challenge name>`\nExample: `>chall web JWT Confused`")
        return
    
    category = parts[0].lower()
    chall_name = parts[1].strip()
    
    if not chall_name:
        await message.channel.send("Challenge name cannot be empty!")
        return
    
    # Create thread with format: [category] challenge name 
    thread_name = f"[{category}] {chall_name} "
    
    try:
        thread = await message.channel.create_thread(
            name=thread_name[:100],  # Discord limit
            type=discord.ChannelType.public_thread,
            reason=f"Challenge created by {message.author.name}"
        )
        
        # Store in JSON
        challenges = load_challenges()
        channel_id = str(message.channel.id)
        
        if channel_id not in challenges:
            challenges[channel_id] = {}
        
        challenges[channel_id][str(thread.id)] = {
            "name": chall_name,
            "category": category,
            "status": "unsolved",
            "created_by": str(message.author.id),
            "created_at": datetime.now().isoformat(),
            "solvers": [],
            "working": []
        }
        
        save_challenges(challenges)
        
        # Send initial message in thread
        await thread.send(
            f"**Challenge: {chall_name}**\n"
            f"Category: `{category}`\n"
            f"Created by: {message.author.mention}\n"
            f"---\n"
            f"Commands:\n"
            f"- `/solved` - Mark as solved\n"
            f"- `/unsolved` - Reset to unsolved\n"
            f"- `/status` - View all challenges"
        )
        
        await message.channel.send(f"Created challenge thread: {thread.mention}")
        
    except discord.Forbidden:
        await message.channel.send("I don't have permission to create threads!")
    except Exception as e:
        await message.channel.send(f"Failed to create thread: {str(e)}")


async def handle_chall_solved(message):
    """
    Mark a challenge as solved.
    Usage: >solved (run inside a challenge thread)
    """
    # Must be in a thread
    if not isinstance(message.channel, discord.Thread):
        await message.channel.send("This command only works inside a challenge thread!")
        return
    
    thread = message.channel
    parent_channel = thread.parent
    
    if not parent_channel or not is_active_ctf(parent_channel):
        await message.channel.send("This thread is not in a CTF channel!")
        return
    
    challenges = load_challenges()
    channel_id = str(parent_channel.id)
    thread_id = str(thread.id)
    
    if channel_id not in challenges or thread_id not in challenges[channel_id]:
        await message.channel.send("This thread is not tracked as a challenge!")
        return
    
    chall = challenges[channel_id][thread_id]
    
    # Calculate solve time
    created = datetime.fromisoformat(chall["created_at"])
    now = datetime.now()
    delta = now - created
    hours, remainder = divmod(int(delta.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)
    
    if hours > 0:
        time_str = f"{hours}h {minutes}m"
    elif minutes > 0:
        time_str = f"{minutes}m {seconds}s"
    else:
        time_str = f"{seconds}s"
    
    # Add solver to list
    user_id = str(message.author.id)
    if "solvers" not in chall:
        chall["solvers"] = []
    
    # Check if already solved by this user
    already_solved = any(s["user_id"] == user_id for s in chall["solvers"])
    if already_solved:
        await message.channel.send(f"{message.author.mention} already solved this!")
        return
    
    chall["solvers"].append({
        "user_id": user_id,
        "solved_at": now.isoformat(),
        "time_str": time_str
    })
    chall["status"] = "solved"
    
    save_challenges(challenges)
    
    # Update thread name if first solver
    old_name = thread.name.replace("[SOLVED]", "").strip()
    new_name = f"{old_name} [SOLVED]"
    
    if len(chall["solvers"]) == 1:  # First solver
        try:
            await thread.edit(name=new_name[:100])
        except:
            pass
    
    solver_count = len(chall["solvers"])
    if solver_count == 1:
        await message.channel.send(
            f"**SOLVED!**\n"
            f"Solved by: {message.author.mention}\n"
            f"Time: {time_str}"
        )
        # Announce in parent channel
        await parent_channel.send(
            f"**{chall['name']}** [{chall['category']}] solved by {message.author.mention}! ({time_str})"
        )
    else:
        await message.channel.send(
            f"{message.author.mention} also solved this! (#{solver_count}, {time_str})"
        )


async def handle_chall_working(message):
    """
    Mark yourself as working on a challenge.
    Usage: >working (run inside a challenge thread)
    """
    if not isinstance(message.channel, discord.Thread):
        await message.channel.send("This command only works inside a challenge thread!")
        return
    
    thread = message.channel
    parent_channel = thread.parent
    
    if not parent_channel or not is_active_ctf(parent_channel):
        await message.channel.send("This thread is not in a CTF channel!")
        return
    
    challenges = load_challenges()
    channel_id = str(parent_channel.id)
    thread_id = str(thread.id)
    
    if channel_id not in challenges or thread_id not in challenges[channel_id]:
        await message.channel.send("This thread is not tracked as a challenge!")
        return
    
    chall = challenges[channel_id][thread_id]
    
    # Add user to working list
    user_id = str(message.author.id)
    if user_id not in chall["working"]:
        chall["working"].append(user_id)
    
    # Update status if unsolved
    if chall["status"] == "unsolved":
        chall["status"] = "working"
    
    save_challenges(challenges)
    
    await message.channel.send(f"{message.author.mention} is working on this!")


async def handle_chall_unsolved(message):
    """
    Mark a challenge back to unsolved.
    Usage: >unsolved (run inside a challenge thread)
    """
    if not isinstance(message.channel, discord.Thread):
        await message.channel.send("This command only works inside a challenge thread!")
        return
    
    thread = message.channel
    parent_channel = thread.parent
    
    if not parent_channel or not is_active_ctf(parent_channel):
        await message.channel.send("This thread is not in a CTF channel!")
        return
    
    challenges = load_challenges()
    channel_id = str(parent_channel.id)
    thread_id = str(thread.id)
    
    if channel_id not in challenges or thread_id not in challenges[channel_id]:
        await message.channel.send("This thread is not tracked as a challenge!")
        return
    
    chall = challenges[channel_id][thread_id]
    
    # Reset status
    chall["status"] = "unsolved"
    chall["solvers"] = []
    chall["working"] = []
    
    save_challenges(challenges)
    
    # Update thread name
    old_name = thread.name.replace("[SOLVED]", "").strip()
    
    try:
        await thread.edit(name=old_name[:100])
    except:
        pass
    
    await message.channel.send("Challenge marked as unsolved.")


async def handle_chall_status(bot, message):
    """
    Show status of all challenges in the CTF.
    Usage: >status (run in CTF channel)
    """
    if not is_active_ctf(message.channel):
        await message.channel.send("This command only works in CTF channels!")
        return
    
    challenges = load_challenges()
    channel_id = str(message.channel.id)
    
    if channel_id not in challenges or not challenges[channel_id]:
        await message.channel.send("No challenges tracked yet!\nUse `>chall <category> <name>` to create one.")
        return
    
    challs = challenges[channel_id]
    
    # Group by category
    by_category = {}
    for thread_id, chall in challs.items():
        cat = chall["category"]
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append((thread_id, chall))
    
    # Build status message
    lines = ["**Challenge Status**\n"]
    
    total_solved = 0
    total_challs = len(challs)
    
    for category in sorted(by_category.keys()):
        cat_challs = by_category[category]
        solved_in_cat = sum(1 for _, c in cat_challs if c["status"] == "solved")
        
        lines.append(f"**[{category.upper()}]** ({solved_in_cat}/{len(cat_challs)})")
        
        for thread_id, chall in cat_challs:
            emoji = get_status_emoji(chall["status"])
            name = chall["name"]
            
            # Try to get thread mention
            thread = message.channel.get_thread(int(thread_id))
            if thread:
                name = thread.mention
            
            extra = ""
            if chall["status"] == "solved":
                solvers = chall.get("solvers", [])
                if solvers:
                    solver_list = ", ".join(f"<@{s['user_id']}>" for s in solvers[:3])
                    if len(solvers) > 3:
                        solver_list += f" +{len(solvers) - 3}"
                    extra = f" - {solver_list}"
            elif chall["status"] == "working" and chall["working"]:
                workers = ", ".join(f"<@{uid}>" for uid in chall["working"][:3])
                if len(chall["working"]) > 3:
                    workers += f" +{len(chall['working']) - 3}"
                extra = f" - {workers}"
            
            lines.append(f"  {emoji} {name}{extra}")
            
            if chall["status"] == "solved":
                total_solved += 1
        
        lines.append("")  # Blank line between categories
    
    # Summary
    lines.insert(1, f"**Progress: {total_solved}/{total_challs}** challenges solved\n")
    
    await message.channel.send("\n".join(lines))
