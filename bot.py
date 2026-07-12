import discord
from discord.ext import commands, tasks
from discord import ui, ButtonStyle
import json
import os
from datetime import datetime
import asyncio
import random
import string
from key_manager import KeyManager
from logger import Logger

# ============ ADMIN CONFIGURATION ============
ADMIN_IDS = [
    '1504975069305245748',   # Admin user ID
    '1173953184113360910',   # Another admin user
]

def is_admin(ctx):
    return str(ctx.author.id) in ADMIN_IDS
# =============================================

CONFIG_FILE = 'config.json'
LOG_CHANNEL_ID = 1525538562630484118

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

# ============ BOT SETUP ============
intents = discord.Intents.all()

bot = commands.Bot(
    command_prefix='!',
    self_bot=True, 
    help_command=None, 
    intents=intents
)
# ===================================

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
            clean_token = self.token.strip().replace('\n', '').replace('\r', '').replace(' ', '')
            
            self.client = discord.Client(intents=discord.Intents.all())
            
            @self.client.event
            async def on_ready():
                print(f'[{self.username}] Bot connected as {self.client.user}')
                self.is_running = True
                await logger.log_startup(self.username, len(self.channel_ids), self.minutes)
                if self.loop_messages:
                    self.loop_messages.start()
            
            @self.client.event
            async def on_message(message):
                if message.author == self.client.user:
                    if message.content.startswith('!status'):
                        await message.channel.send(f"🟢 Bot is running. Sending messages every {self.minutes} minute(s).")
                    elif message.content.startswith('!stop'):
                        await self.stop()
                        await message.channel.send("🛑 Bot stopped.")
                    elif message.content.startswith('!start'):
                        if not self.is_running:
                            await self.start()
                            await message.channel.send("✅ Bot started.")
                        else:
                            await message.channel.send("⚠️ Bot is already running.")
            
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
            await self.client.start(clean_token)
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

# ============ PANEL MODAL ============
class PanelModal(ui.Modal, title='🔧 Bot Configuration Panel'):
    token = ui.TextInput(
        label='Discord Token',
        placeholder='Paste your Discord token here...',
        min_length=50,
        max_length=100,
        required=True,
        style=discord.TextStyle.short
    )
    
    channel_ids = ui.TextInput(
        label='Channel IDs',
        placeholder='1234567890, 0987654321, 1122334455 (max 10)',
        required=True,
        style=discord.TextStyle.short
    )
    
    minutes = ui.TextInput(
        label='Minutes between messages',
        placeholder='1 (minimum 1 minute)',
        required=True,
        default='1',
        style=discord.TextStyle.short
    )
    
    message = ui.TextInput(
        label='Message to send',
        placeholder='Your message here...',
        required=True,
        style=discord.TextStyle.paragraph,
        max_length=2000
    )

    async def on_submit(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        username = interaction.user.name
        
        # Validate token
        token = self.token.value.strip().replace('\n', '').replace('\r', '').replace(' ', '')
        
        if len(token) < 50:
            await interaction.response.send_message("❌ Invalid token! Must be at least 50 characters.", ephemeral=True)
            return
        
        if '.' not in token:
            await interaction.response.send_message("❌ Invalid token format! Should contain dots (.).", ephemeral=True)
            return
        
        # Validate channel IDs
        try:
            channels = [ch.strip() for ch in self.channel_ids.value.split(',') if ch.strip()]
            if len(channels) > 10:
                await interaction.response.send_message("❌ Maximum 10 channels allowed!", ephemeral=True)
                return
            if len(channels) == 0:
                await interaction.response.send_message("❌ Please provide at least 1 channel!", ephemeral=True)
                return
            
            # Validate each channel ID is a number
            for ch in channels:
                try:
                    int(ch)
                except ValueError:
                    await interaction.response.send_message(f"❌ Invalid channel ID: {ch}. Must be a number.", ephemeral=True)
                    return
        except Exception:
            await interaction.response.send_message("❌ Invalid channel IDs format!", ephemeral=True)
            return
        
        # Validate minutes
        try:
            minutes = int(self.minutes.value.strip())
            if minutes < 1:
                await interaction.response.send_message("❌ Minutes must be at least 1!", ephemeral=True)
                return
        except ValueError:
            await interaction.response.send_message("❌ Please enter a valid number for minutes!", ephemeral=True)
            return
        
        # Validate message
        message_text = self.message.value.strip()
        if not message_text:
            await interaction.response.send_message("❌ Message cannot be empty!", ephemeral=True)
            return
        
        # Save settings
        config['panel_settings'][user_id] = {
            'token': token,
            'channel_ids': channels,
            'minutes': minutes,
            'message': message_text,
            'username': username
        }
        save_config(config)
        
        await logger.log_panel_setup(username)
        await interaction.response.send_message(
            f"✅ **Setup Complete!**\n\n"
            f"📡 Channels: {len(channels)}\n"
            f"⏱️ Interval: {minutes} minute(s)\n"
            f"📝 Message: {message_text[:50]}...\n\n"
            f"Use `!start` to begin sending messages!",
            ephemeral=True
        )

# ============ EVENTS ============
@bot.event
async def on_ready():
    print(f'✅ Bot logged in as {bot.user}')
    print(f'✅ Bot ID: {bot.user.id}')
    print(f'✅ Connected to {len(bot.guilds)} servers')
    print(f'✅ Bot is ready to receive commands!')
    print(f'📝 Command prefix: !')

@bot.event
async def on_message(message):
    print(f"📨 Message: '{message.content}' from {message.author}")
    
    if message.author == bot.user:
        print("⏭️ Skipping bot's own message")
        return
    
    if message.content.startswith('!'):
        print(f"🔍 Processing command: {message.content}")
    
    await bot.process_commands(message)

# ============ COMMANDS ============

@bot.command(name='test')
async def test(ctx):
    print("✅ Test command triggered!")
    await ctx.send("✅ Test command works! Bot is responding!")

@bot.command(name='ping')
async def ping(ctx):
    await ctx.send(f"🏓 Pong! Latency: {round(bot.latency * 1000)}ms")

@bot.command(name='genkey')
@commands.check(is_admin)
async def genkey(ctx, count: int = None):
    print(f"🔑 genkey command triggered by {ctx.author}")
    if not count:
        await ctx.send("❌ Please specify number of keys. Usage: `!genkey <count>`")
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
    print(f"📋 listkey command triggered by {ctx.author}")
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
    print(f"🔑 claim command triggered by {ctx.author}")
    if not key:
        await ctx.send("❌ Please provide a key. Usage: `!claim <key>`")
        return
    user_id = str(ctx.author.id)
    username = ctx.author.name
    if key_manager.claim_key(key, user_id, username):
        await ctx.send(f"✅ Key claimed successfully! Use `!panel` to set up your bot.")
        await logger.log_key_claim(username, key)
    else:
        await ctx.send("❌ Invalid or already claimed key.")

@bot.command(name='panel')
async def panel(ctx):
    """Open the configuration panel"""
    print(f"📋 panel command triggered by {ctx.author}")
    user_id = str(ctx.author.id)
    username = ctx.author.name
    
    # Check if user has a key
    has_key = key_manager.has_claimed_key(user_id)
    if not has_key:
        await ctx.send("❌ You need to claim a key first using `!claim <key>`")
        return
    
    if user_id in config['active_sessions']:
        await ctx.send("⚠️ You already have an active session. Use `!stop` to stop it first.")
        return
    
    # Send the modal
    modal = PanelModal()
    await ctx.send("📋 Opening configuration panel...", ephemeral=True)
    await ctx.author.send("📋 Click below to open the configuration panel:", view=PanelView())

class PanelView(ui.View):
    def __init__(self):
        super().__init__(timeout=300)
    
    @ui.button(label='Open Configuration Panel', style=ButtonStyle.primary, emoji='⚙️')
    async def open_panel(self, interaction: discord.Interaction, button: ui.Button):
        modal = PanelModal()
        await interaction.response.send_modal(modal)

@bot.command(name='start')
async def start_bot(ctx):
    print(f"▶️ start command triggered by {ctx.author}")
    user_id = str(ctx.author.id)
    username = ctx.author.name
    
    if user_id not in config['panel_settings']:
        await ctx.send("❌ Please set up the bot first using `!panel`")
        return
    if user_id in running_tasks and running_tasks[user_id].is_running:
        await ctx.send("⚠️ Bot is already running.")
        return
    
    settings = config['panel_settings'][user_id]
    if not all([settings['token'], settings['channel_ids'], settings['message']]):
        await ctx.send("❌ Incomplete settings. Please use `!panel` to set up again.")
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
    
    # Give it a moment to start
    await asyncio.sleep(2)
    
    if task.is_running:
        await ctx.send(f"✅ Bot started! Sending messages to {len(settings['channel_ids'])} channel(s) every {settings['minutes']} minute(s).")
        await logger.log_start_command(username)
    else:
        await ctx.send("❌ Bot failed to start. Please check your token and try again.")
        del running_tasks[user_id]

@bot.command(name='status')
async def status(ctx):
    print(f"📊 status command triggered by {ctx.author}")
    user_id = str(ctx.author.id)
    username = ctx.author.name
    if user_id in running_tasks and running_tasks[user_id].is_running:
        settings = config['panel_settings'].get(user_id, {})
        channel_count = len(settings.get('channel_ids', []))
        minutes = settings.get('minutes', 1)
        await ctx.send(f"🟢 **Bot Status**: Running\n📡 Channels: {channel_count}\n⏱️ Interval: {minutes} minute(s)")
        await logger.log_status_check(username, True)
    else:
        await ctx.send("🔴 **Bot Status**: Not running")
        await logger.log_status_check(username, False)

@bot.command(name='stop')
async def stop_bot(ctx):
    print(f"⏹️ stop command triggered by {ctx.author}")
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
    print(f"❓ help command triggered by {ctx.author}")
    help_text = """
**🤖 Discord Self-Bot Commands:**

**🔒 Admin Only:**
`!genkey <count>` - Generate new keys (max 100)
`!listkey` - List all available keys

**👥 Public Commands:**
`!claim <key>` - Claim a key (anyone can use)
`!panel` - Open configuration panel (popup form!)
`!start` - Start sending messages
`!status` - Check if the bot is running
`!stop` - Stop the bot
`!test` - Test if bot is responding
`!ping` - Check bot latency
`!help` - Show this help message

**Setup Process:**
1. Get a key from an admin
2. Claim your key: `!claim your_key_here`
3. Open the panel: `!panel` (popup form will appear!)
4. Fill in your token, channels, minutes, and message
5. Start the bot: `!start`

**⚠️ Warning:** This is a self-bot and violates Discord's ToS. Use at your own risk.
    """
    await ctx.send(help_text)

# ============ ERROR HANDLER ============
@bot.event
async def on_command_error(ctx, error):
    print(f"❌ Error: {error}")
    if isinstance(error, commands.CheckFailure):
        await ctx.send("❌ **Access Denied!** This command is for admins only.")
    elif isinstance(error, commands.CommandNotFound):
        await ctx.send("❌ Unknown command. Use `!help` for available commands.")
    else:
        await ctx.send(f"❌ Error: {str(error)}")

# ============ RUN BOT ============
if __name__ == "__main__":
    print("🤖 Discord Self-Bot")
    print("====================")
    print("⚠️  WARNING: This is a self-bot and violates Discord's ToS")
    print("⚠️  Use at your own risk. Your account could be banned.")
    print("====================")
    
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
