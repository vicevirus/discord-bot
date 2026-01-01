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
    # Anonymous
    'handle_anonymous_question',
    # Help
    'send_help_message',
    'send_writeup_help',
    'HELP_MESSAGE',
    'WRITEUP_HELP_MESSAGE',
    'SLASH_HELP_MESSAGE',
    'SLASH_WRITEUP_HELP_MESSAGE',
]
