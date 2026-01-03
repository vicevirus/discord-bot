"""
Handlers package - all message and event handlers.
"""

from handlers.ctf import (
    handle_ctf_create,
    handle_ctf_archive,
    display_upcoming_ctfs,
    create_category_if_not_exists,
    get_current_year,
    get_current_year_short,
    update_year,
)

from handlers.writeup import (
    handle_quick_writeup,
    handle_batch_writeup,
    handle_writeup_delete,
    slash_delete_writeup,
    writeup_autocomplete,
)

from handlers.anonymous import (
    handle_anonymous_question,
)

from handlers.help import (
    send_help_message,
    send_writeup_help,
    HELP_MESSAGE,
    WRITEUP_HELP_MESSAGE,
    SLASH_HELP_MESSAGE,
    SLASH_WRITEUP_HELP_MESSAGE,
)

from handlers.challenge import (
    handle_chall_create,
    handle_chall_solved,
    handle_chall_working,
    handle_chall_unsolved,
    handle_chall_status,
    # Slash command handlers
    create_challenge_thread,
    mark_solved,
    mark_unsolved,
    show_status,
    delete_challenge,
    auto_track_worker,
)

__all__ = [
    # CTF
    'handle_ctf_create',
    'handle_ctf_archive',
    'display_upcoming_ctfs',
    'create_category_if_not_exists',
    'get_current_year',
    'get_current_year_short',
    'update_year',
    # Writeup
    'handle_quick_writeup',
    'handle_batch_writeup',
    'handle_writeup_delete',
    'slash_delete_writeup',
    'writeup_autocomplete',
    # Anonymous
    'handle_anonymous_question',
    # Help
    'send_help_message',
    'send_writeup_help',
    'HELP_MESSAGE',
    'WRITEUP_HELP_MESSAGE',
    'SLASH_HELP_MESSAGE',
    'SLASH_WRITEUP_HELP_MESSAGE',
    # Challenge tracking (legacy prefix)
    'handle_chall_create',
    'handle_chall_solved',
    'handle_chall_working',
    'handle_chall_unsolved',
    'handle_chall_status',
    # Challenge tracking (slash commands)
    'create_challenge_thread',
    'mark_solved',
    'mark_unsolved',
    'show_status',
    'delete_challenge',
    'auto_track_worker',
]
