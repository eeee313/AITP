import discord
from discord.ext import commands, tasks
import json
import os
from datetime import datetime
import asyncio
import random
import string
from key_manager import KeyManager
from logger import Logger

# ============ ADMIN CONFIGURATION ============
# ONLY this user can use /genkey and /listkey
ADMIN_IDS = [
    '1504975069305245748',  # Admin user ID
]

def is_admin(ctx):
    """Check if user is an admin"""
    return str(ctx.author.id) in ADMIN_IDS
# =============================================

# Configuration file
CONFIG_FILE = 'config.json'
LOG_CHANNEL_ID = 1525538562630484118  # Your log channel ID

# Load or create config
def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {
        'claimed_keys': {},
        'active_sessions': {},
        'panel_settings': {},
        'keys': {}
    }

def save_config(config):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=4)

config = load_config()
key_manager = KeyManager(config)
logger = Logger(LOG_CHANNEL_ID)

# Bot setup
bot = commands.Bot(command_prefix='/', self_bot=True, help_command=None)

# Dictionary to store running tasks
running_tasks = {}

class MessageTask:
    def __init__(self, token, channel_ids, minutes, message, user_id, username):
        self.token = token
        self.channel_ids = channel_ids
        self.minutes = minutes
        self.message = message
        self.user_id = user_id
        self.username = username
        self.is_running = False
        self.task = None
        self.client = None
        self.loop_messages = None

    async def start(self):
        if self.is_running:
            return False
        
        try:
            self.client = discord.Client()
            
            @self.client.event
            async def on_ready():
                print(f'[{self.username}] Bot connected as {self.client.user}')
                self.is_running = True
                
                # Log startup
                await logger.log_startup(self.username, len(self.channel_ids), self.minutes)
                
                # Start the scheduled task
                if self.loop_messages:
                    self.loop_messages.start()
            
            @self.client.event
            async def on_message(message):
                if message.author == self.client.user:
                    if message.content.startswith('/status'):
                        await message.channel.send(f"🟢 Bot is running. Sending messages every {self.minutes} minute(s).")
                    elif message.content.startswith('/stop'):
                        await self.stop()
                        await message.channel.send("🛑 Bot stopped.")
                    elif message.content.startswith('/start'):
                        if not self.is_running:
                            await self.start()
                            await message.channel.send("✅ Bot started.")
                        else:
                            await message.channel.send("⚠️ Bot is already running.")
            
            @self.client.event
            async def on_ready():
                print(f'[{self.username}] Bot ready!')
            
            @tasks.loop(minutes=self.minutes)
            async def loop_messages():
                if not self.is_running:
                    return
                
                try:
                    for channel_id in self.channel_ids:
                        channel = self.client.get_channel(int(channel_id))
                        if channel:
                            await channel.send(self.message)
                            print(f'[{self.username}] Sent message to {channel_id}')
                            await logger.log_message_sent(self.username, channel_id, self.message[:50])
                        else:
                            print(f'[{self.username}] Channel {channel_id} not found')
                            await logger.log_error(self.username, f"Channel {channel_id} not found")
                except Exception as e:
                    print(f'[{self.username}] Error sending message: {e}')
                    await logger.log_error(self.username, str(e))
            
            self.loop_messages = loop_messages
            
            await self.client.start(self.token)
            return True
            
        except Exception as e:
            print(f'[{self.username}] Error starting bot: {e}')
            await logger.log_error(self.username, f"Start error: {str(e)}")
            return False

    async def stop(self):
        self.is_running = False
        if self.loop_messages:
            self.loop_messages.cancel()
        if self.client:
            await self.client.close()
        await logger.log_stop(self.username)
        return True

# ============ COMMANDS ============

@bot.command(name='genkey')
@commands.check(is_admin)
async def genkey(ctx, count: int = None):
    """Generate new keys (max 100 per command) - ADMIN ONLY"""
    if not count:
        await ctx.send("❌ Please specify number of keys. Usage: `/genkey <count>`")
        return
    
    if count < 1:
        await ctx.send("❌ Count must be at least 1.")
        return
    
    if count > 100:
        await ctx.send("❌ Maximum 100 keys per generation.")
        return
    
    keys = key_manager.generate_keys(count)
    
    if keys:
        key_list = '\n'.join(keys)
        await ctx.send(f"✅ Generated {len(keys)} key(s):\n```\n{key_list}\n```")
        await logger.log_key_generation(ctx.author.name, len(keys))
    else:
        await ctx.send("❌ Failed to generate keys.")

@bot.command(name='listkey')
@commands.check(is_admin)
async def listkey(ctx):
    """List all available keys - ADMIN ONLY"""
    available_keys = key_manager.list_keys()
    
    if not available_keys:
        await ctx.send("📭 No available keys.")
        return
    
    display_keys = available_keys[:10]
    key_list = '\n'.join(display_keys)
    total = len(available_keys)
    
    if total > 10:
        await ctx.send(f"📋 Available keys ({total} total, showing first 10):\n```\n{key_list}\n```")
    else:
        await ctx.send(f"📋 Available keys ({total} total):\n```\n{key_list}\n```")
    
    await logger.log_list_keys(ctx.author.name)

@bot.command(name='claim')
async def claim(ctx, key=None):
    """Claim a key to use the bot"""
    if not key:
        await ctx.send("❌ Please provide a key. Usage: `/claim <key>`")
        return
    
    user_id = str(ctx.author.id)
    username = ctx.author.name
    
    if key_manager.claim_key(key, user_id, username):
        await ctx.send(f"✅ Key claimed successfully! Use `/panel` to set up your bot.")
        await logger.log_key_claim(username, key)
    else:
        await ctx.send("❌ Invalid or already claimed key.")

@bot.command(name='panel')
async def panel(ctx):
    """Set up the bot configuration"""
    user_id = str(ctx.author.id)
    username = ctx.author.name
    
    has_key = key_manager.has_claimed_key(user_id)
    if not has_key:
        await ctx.send("❌ You need to claim a key first using `/claim <key>`")
        return
    
    if user_id in config['active_sessions']:
        await ctx.send("⚠️ You already have an active session. Use `/stop` to stop it first.")
        return
    
    config['panel_settings'][user_id] = {
        'token': None,
        'channel_ids': [],
        'minutes': 1,
        'message': None,
        'username': username
    }
    save_config(config)
    
    await ctx.send("""📋 **Panel Setup**
Please provide the following information (one per line):
1. Discord Token
2. Channel IDs (comma-separated, max 10)
3. Minutes between messages (1 minute = 1 message)
4. Message to send

Example:
`token_here`
`1234567890,0987654321`
`5`
`Hello everyone!`

Type `/done` when finished.
Type `/cancel` to cancel.
""")

    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel
    
    required_fields = ['token', 'channel_ids', 'minutes', 'message']
    field_index = 0
    
    while field_index < len(required_fields):
        try:
            msg = await bot.wait_for('message', timeout=300.0, check=check)
            
            if msg.content.lower() == '/cancel':
                del config['panel_settings'][user_id]
                save_config(config)
                await ctx.send("❌ Setup cancelled.")
                return
            
            if msg.content.lower() == '/done':
                if field_index > 0:
                    break
                else:
                    await ctx.send("❌ You haven't provided all required information yet.")
                    continue
            
            if field_index == 0:  # token
                config['panel_settings'][user_id]['token'] = msg.content.strip()
            elif field_index == 1:  # channel_ids
                try:
                    channels = [ch.strip() for ch in msg.content.split(',') if ch.strip()]
                    if len(channels) > 10:
                        await ctx.send("❌ Maximum 10 channels allowed. Please try again.")
                        continue
                    config['panel_settings'][user_id]['channel_ids'] = channels
                except Exception:
                    await ctx.send("❌ Invalid channel IDs. Please use comma-separated numbers.")
                    continue
            elif field_index == 2:  # minutes
                try:
                    minutes = int(msg.content.strip())
                    if minutes < 1:
                        await ctx.send("❌ Minutes must be at least 1.")
                        continue
                    config['panel_settings'][user_id]['minutes'] = minutes
                except ValueError:
                    await ctx.send("❌ Please enter a valid number.")
                    continue
            elif field_index == 3:  # message
                config['panel_settings'][user_id]['message'] = msg.content.strip()
            
            field_index += 1
            
            if field_index < len(required_fields):
                await ctx.send(f"✅ Received. Next: {required_fields[field_index].title()}")
            
        except asyncio.TimeoutError:
            await ctx.send("❌ Setup timed out. Please start over with `/panel`")
            del config['panel_settings'][user_id]
            save_config(config)
            return
    
    save_config(config)
    await logger.log_panel_setup(username)
    await ctx.send("✅ Setup complete! Use `/start` to begin sending messages.")

@bot.command(name='start')
async def start_bot(ctx):
    """Start the message sending bot"""
    user_id = str(ctx.author.id)
    username = ctx.author.name
    
    if user_id not in config['panel_settings']:
        await ctx.send("❌ Please set up the bot first using `/panel`")
        return
    
    if user_id in running_tasks and running_tasks[user_id].is_running:
        await ctx.send("⚠️ Bot is already running.")
        return
    
    settings = config['panel_settings'][user_id]
    
    if not all([settings['token'], settings['channel_ids'], settings['message']]):
        await ctx.send("❌ Incomplete settings. Please use `/panel` to set up again.")
        return
    
    task = MessageTask(
        settings['token'],
        settings['channel_ids'],
        settings['minutes'],
        settings['message'],
        user_id,
        username
    )
    
    running_tasks[user_id] = task
    bot.loop.create_task(task.start())
    
    await ctx.send(f"✅ Bot started! Sending messages to {len(settings['channel_ids'])} channel(s) every {settings['minutes']} minute(s).")
    await logger.log_start_command(username)

@bot.command(name='status')
async def status(ctx):
    """Check if the bot is running"""
    user_id = str(ctx.author.id)
    username = ctx.author.name
    
    if user_id in running_tasks and running_tasks[user_id].is_running:
        settings = config['panel_settings'].get(user_id, {})
        channel_count = len(settings.get('channel_ids', []))
        minutes = settings.get('minutes', 1)
        await ctx.send(f"🟢 **Bot Status**: Running\n"
                      f"📡 Channels: {channel_count}\n"
                      f"⏱️ Interval: {minutes} minute(s)")
        await logger.log_status_check(username, True)
    else:
        await ctx.send("🔴 **Bot Status**: Not running")
        await logger.log_status_check(username, False)

@bot.command(name='stop')
async def stop_bot(ctx):
    """Stop the bot"""
    user_id = str(ctx.author.id)
    username = ctx.author.name
    
    if user_id not in running_tasks:
        await ctx.send("❌ No active bot session found.")
        return
    
    task = running_tasks[user_id]
    if task.is_running:
        await task.stop()
        del running_tasks[user_id]
        await ctx.send("🛑 Bot stopped successfully!")
        await logger.log_stop_command(username)
    else:
        await ctx.send("❌ Bot is not running.")

@bot.command(name='help')
async def help_command(ctx):
    """Show available commands"""
    help_text = """
**🤖 Discord Self-Bot Commands:**

**Admin Commands:**
`/genkey <count>` - Generate new keys (max 100) - Admin Only
`/listkey` - List all available keys - Admin Only

**User Commands:**
`/claim <key>` - Claim a key to use the bot
`/panel` - Set up your bot configuration
`/start` - Start sending messages
`/status` - Check if the bot is running
`/stop` - Stop the bot
`/help` - Show this help message

**Setup Process:**
1. Get a key from an admin
2. Claim your key: `/claim your_key_here`
3. Set up your configuration: `/panel`
4. Start the bot: `/start`

**⚠️ Warning:** This is a self-bot and violates Discord's ToS. Use at your own risk.
    """
    await ctx.send(help_text)

# ============ ERROR HANDLER ============
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CheckFailure):
        await ctx.send("❌ **Access Denied!** This command is for admins only.")
    elif isinstance(error, commands.CommandNotFound):
        await ctx.send("❌ Unknown command. Use `/help` for available commands.")
    else:
        await ctx.send(f"❌ Error: {str(error)}")

# ============ RUN BOT ============
if __name__ == "__main__":
    print("🤖 Discord Self-Bot")
    print("====================")
    print("⚠️  WARNING: This is a self-bot and violates Discord's ToS")
    print("⚠️  Use at your own risk. Your account could be banned.")
    print("====================")
    
    # Get token from environment variable (Railway) or prompt user
    token = os.getenv('BOT_TOKEN')
    if not token:
        token = input("Enter your Discord token: ").strip()
    
    if not token:
        print("❌ No token provided!")
        print("Please set BOT_TOKEN environment variable or enter token manually.")
        exit(1)
    
    try:
        bot.run(token)
    except discord.LoginFailure:
        print("❌ Invalid token. Please try again.")
    except Exception as e:
        print(f"❌ Error: {e}")
# ===================================
