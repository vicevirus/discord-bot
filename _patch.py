content = open('bot.py').read()

old = (
    "            elif message.content.startswith('>bot help'):\n"
    "                await send_help_message(message.channel)\n"
    "        else:\n"
    "            await message.channel.send(\"You must be a member of the server to use this command.\")"
)

new = (
    "            elif message.content.startswith('>bot help'):\n"
    "                await send_help_message(message.channel)\n"
    "            else:\n"
    "                user_input = message.content.strip()\n"
    "                if user_input.lower() in ('clear', 'reset', 'forget'):\n"
    "                    clear_channel_history(message.channel.id)\n"
    "                    await message.channel.send('\U0001f9f9 Cleared.')\n"
    "                    return\n"
    "                if user_input:\n"
    "                    async with message.channel.typing():\n"
    "                        try:\n"
    "                            reply = await handle_agent_message(message.channel.id, user_input)\n"
    "                            if len(reply) > 1900:\n"
    "                                for i in range(0, len(reply), 1900):\n"
    "                                    await message.channel.send(reply[i:i+1900])\n"
    "                            else:\n"
    "                                await message.channel.send(reply)\n"
    "                        except Exception as e:\n"
    "                            await message.channel.send(f'Agent error: {e}')\n"
    "        else:\n"
    "            await message.channel.send(\"You must be a member of the server to use this command.\")"
)

assert old in content, f'Pattern not found!'
open('bot.py', 'w').write(content.replace(old, new, 1))
print('Done')
