module.exports = {
  apps: [{
    name: 'discord-bot',
    script: 'bot.py',
    interpreter: '/root/discord-bot/venv/bin/python3',
    cwd: '/root/discord-bot',
    watch: false,
    autorestart: true,
    max_restarts: 10,
    restart_delay: 5000,
    env: {
      NODE_ENV: 'production'
    }
  }]
};
