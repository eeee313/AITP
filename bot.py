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

# CHANGE THIS PREFIX TO WHATEVER YOU WANT (e.g., '$')
bot = commands.Bot(
    command_prefix='!',   # <--- set to '!' for all commands
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
        # Bypass mode (default from config)
        self.bypass_mode = config.get('panel_settings', {}).get(user_id, {}).get('bypass', False)

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
                    # Only handle commands if they match the main bot's prefix
                    # We'll just handle status/stop/start inside the task for convenience
                    content = message.content
                    if content.startswith('!status'):   # hardcoded ! for task commands
                        await message.channel.send(f"🟢 Bot is running. Sending messages every {self.minutes} minute(s).")
                    elif content.startswith('!stop'):
                        await self.stop()
                        await message.channel.send("🛑 Bot stopped.")
                    elif content.startswith('!start'):
                        if not self.is_running:
                            await self.start()
                            await message.channel.send("✅ Bot started.")
                        else:
                            await message.channel.send("⚠️ Bot is already running.")
                    elif content.startswith('!bypasson'):
                        self.bypass_mode = True
                        config['panel_settings'][self.user_id]['bypass'] = True
                        save_config(config)
                        await message.channel.send("🔄 Bypass mode **ON** – delays and jitter added.")
                        await logger.log_bypass(self.username, True)
                    elif content.startswith('!bypassoff'):
                        self.bypass_mode = False
                        config['panel_settings'][self.user_id]['bypass'] = False
                        save_config(config)
                        await message.channel.send("🔄 Bypass mode **OFF** – normal speed.")
                        await logger.log_bypass(self.username, False)
            
            @tasks.loop(minutes=self.minutes)
            async def loop_messages():
                if not self.is_running:
                    return
                try:
                    for channel_id in self.channel_ids:
                        channel = self.client.get_channel(int(channel_id))
                        if channel:
                            await self._send_with_bypass(channel)
                        else:
                            print(f'[{self.username}] Channel {channel_id} not found')
                            await logger.log_error(self.username, f"Channel {channel_id} not found")
                except Exception as e:
                    print(f'[{self.username}] Error sending message: {e}')
                    await logger.log_error(self.username, str(e))
            
            self.loop_messages = loop_messages
            await self.client.start(clean_token)
            return True
            
        except discord.LoginFailure as e:
            print(f'[{self.username}] Login failed: {e}')
            await logger.log_error(self.username, f"Login failed: Invalid token")
            return False
        except Exception as e:
            print(f'[{self.username}] Error starting bot: {e}')
            await logger.log_error(self.username, f"Start error: {str(e)}")
            return False

    async def _send_with_bypass(self, channel):
        """Send a message with bypass logic (delays, retries, rate-limit sensing)"""
        MAX_RETRIES = 5
        retries = 0
        while retries < MAX_RETRIES:
            try:
                # If bypass is ON, add a random delay (5-15s) before sending
                if self.bypass_mode:
                    await asyncio.sleep(random.uniform(5, 15))
                
                await channel.send(self.message)
                print(f'[{self.username}] Sent message to {channel.id}')
                await logger.log_message_sent(self.username, channel.id, self.message[:50])
                break  # success, exit loop
            except discord.HTTPException as e:
                # Rate limit (429) detection
                if e.status == 429:
                    retry_after = e.retry_after if hasattr(e, 'retry_after') else 5
                    print(f'[{self.username}] Rate limited! Retry after {retry_after}s')
                    await logger.log_error(self.username, f"Rate limited, retrying in {retry_after}s")
                    await asyncio.sleep(retry_after)
                    retries += 1
                else:
                    print(f'[{self.username}] HTTP error: {e}')
                    await logger.log_error(self.username, f"HTTP error: {str(e)}")
                    break
            except Exception as e:
                print(f'[{self.username}] Unexpected error: {e}')
                await logger.log_error(self.username, f"Unexpected error: {str(e)}")
                break
        else:
            print(f'[{self.username}] Failed to send message after {MAX_RETRIES} retries.')

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
        label='Discord Token (USER TOKEN)',
        placeholder='Paste your Discord USER token from browser Local Storage',
        min_length=50,
        max_length=120,
        required=True,
        style=discord.TextStyle.short
    )
    
    channel_ids = ui.TextInput(
        label='Channel IDs (max 10)',
        placeholder='1234567890, 0987654321, 1122334455',
        required=True,
        style=discord.TextStyle.short
    )
    
    minutes = ui.TextInput(
        label='Minutes between messages',
        placeholder='1 (minimum)',
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
        
        # Clean token
        token = self.token.value.strip().replace('\n', '').replace('\r', '').replace(' ', '')
        
        # === TOKEN VALIDATION ===
        if len(token) < 50:
            await interaction.response.send_message(
                "❌ **Invalid Token!**\n\n"
                "Token must be at least 50 characters long.\n"
                "Make sure you're copying your USER token, not a bot token.\n\n"
                "**How to get your USER token:**\n"
                "1. Open Discord in your BROWSER\n"
                "2. Press F12 → Application → Local Storage\n"
                "3. Find 'token' under https://discord.com\n"
                "4. Copy the value (it changes if you log out/in)",
                ephemeral=True
            )
            return
        
        if token.count('.') < 2:
            await interaction.response.send_message(
                "❌ **Invalid Token Format!**\n\n"
                "Your token should have dots (.) in it.\n"
                "Example: MTIzNDU2Nzg5MDEyMzQ1Njc4OQ.**GENERATED**.**SECRET**\n\n"
                "You might be using a Bot Token instead of a User Token.\n"
                "**User Token:** Found in browser Local Storage ✅\n"
                "**Bot Token:** Found in Discord Developer Portal ❌",
                ephemeral=True
            )
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
            
            for ch in channels:
                try:
                    int(ch)
                except ValueError:
                    await interaction.response.send_message(f"❌ Invalid channel ID: {ch}. Must be a number.", ephemeral=True)
                    return
        except Exception:
            await interaction.response.send_message("❌ Invalid channel IDs format! Use comma-separated numbers.", ephemeral=True)
            return
        
        # Validate minutes
        try:
            minutes = int(self.minutes.value.strip())
            if minutes < 1:
                await interaction.response.send_message("❌ Minutes must be at least 1!", ephemeral=True)
                return
            if minutes > 60:
                await interaction.response.send_message(f"⚠️ Minutes set to {minutes}. This is a long interval!", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("❌ Please enter a valid number for minutes!", ephemeral=True)
            return
        
        # Validate message
        message_text = self.message.value.strip()
        if not message_text:
            await interaction.response.send_message("❌ Message cannot be empty!", ephemeral=True)
            return
        
        # Save settings (preserve existing bypass flag)
        existing_bypass = config.get('panel_settings', {}).get(user_id, {}).get('bypass', False)
        config['panel_settings'][user_id] = {
            'token': token,
            'channel_ids': channels,
            'minutes': minutes,
            'message': message_text,
            'username': username,
            'bypass': existing_bypass
        }
        save_config(config)
        
        await logger.log_panel_setup(username)
        
        # Test token
        await interaction.response.send_message(
            "⏳ **Testing your token...**\n"
            "Please wait while I verify your token is valid.\n"
            "This may take a few seconds...",
            ephemeral=True
        )
        
        try:
            test_client = discord.Client(intents=discord.Intents.default())
            await test_client.login(token)
            await test_client.close()
            
            await interaction.edit_original_response(
                content=f"✅ **Setup Complete!**\n\n"
                f"✅ Token validated successfully!\n"
                f"📡 Channels: {len(channels)}\n"
                f"⏱️ Interval: {minutes} minute(s)\n"
                f"📝 Message: {message_text[:50]}...\n\n"
                f"Use `{bot.command_prefix}start` to begin sending messages!\n"
                f"Toggle bypass with `{bot.command_prefix}bypasson` / `{bot.command_prefix}bypassoff`",
                ephemeral=True
            )
        except discord.LoginFailure:
            del config['panel_settings'][user_id]
            save_config(config)
            await interaction.edit_original_response(
                content=f"❌ **Token Validation Failed!**\n\n"
                f"Your token is invalid or expired.\n\n"
                f"**Common issues:**\n"
                f"• You're using a Bot Token instead of a User Token\n"
                f"• You have extra spaces or characters\n"
                f"• Your token has expired (get a fresh one)\n\n"
                f"**How to get a fresh USER token:**\n"
                f"1. Open Discord in your BROWSER\n"
                f"2. Press F12 → Application → Local Storage\n"
                f"3. Find 'token' under https://discord.com\n"
                f"4. Copy the value (it changes if you log out/in)\n\n"
                f"Please run `{bot.command_prefix}panel` again with the correct token.",
                ephemeral=True
            )
        except Exception as e:
            del config['panel_settings'][user_id]
            save_config(config)
            await interaction.edit_original_response(
                content=f"❌ **Error:** {str(e)}\n\n"
                f"Please run `{bot.command_prefix}panel` again and try with a fresh token.",
                ephemeral=True
            )

# ============ PANEL BUTTON VIEW ============
class PanelView(ui.View):
    def __init__(self):
        super().__init__(timeout=300)
    
    @ui.button(label='Open Configuration Panel', style=ButtonStyle.primary, emoji='⚙️')
    async def open_panel(self, interaction: discord.Interaction, button: ui.Button):
        modal = PanelModal()
        await interaction.response.send_modal(modal)

# ============ EVENTS ============
@bot.event
async def on_ready():
    print(f'✅ Bot logged in as {bot.user}')
    print(f'✅ Bot ID: {bot.user.id}')
    print(f'✅ Connected to {len(bot.guilds)} servers')
    print(f'✅ Bot is ready to receive commands!')
    print(f'📝 Command prefix: {bot.command_prefix}')

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    if message.content.startswith(bot.command_prefix):
        await bot.process_commands(message)

# ============ COMMANDS ============

@bot.command(name='test')
async def test(ctx):
    await ctx.send("✅ Test command works! Bot is responding!")

@bot.command(name='ping')
async def ping(ctx):
    await ctx.send(f"🏓 Pong! Latency: {round(bot.latency * 1000)}ms")

@bot.command(name='genkey')
@commands.check(is_admin)
async def genkey(ctx, count: int = None):
    if not count:
        await ctx.send("❌ Please specify number of keys. Usage: `!genkey <count>`")
        return
    if count < 1 or count > 100:
        await ctx.send("❌ Count must be between 1 and 100.")
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
    available_keys = key_manager.list_keys()
    if not available_keys:
        await ctx.send("📭 No available keys.")
        return
    display_keys = available_keys[:10]
    key_list = '\n'.join(display_keys)
    total = len(available_keys)
    await ctx.send(f"📋 Available keys ({total} total, showing first 10):\n```\n{key_list}\n```")
    await logger.log_list_keys(ctx.author.name)

@bot.command(name='claim')
async def claim(ctx, key=None):
    if not key:
        await ctx.send("❌ Please provide a key. Usage: `!claim <key>`")
        return
    user_id = str(ctx.author.id)
    username = ctx.author.name
    if key_manager.claim_key(key, user_id, username):
        await ctx.send(f"✅ Key claimed successfully! Use `{bot.command_prefix}panel` to set up your bot.")
        await logger.log_key_claim(username, key)
    else:
        await ctx.send("❌ Invalid or already claimed key.")

@bot.command(name='panel')
async def panel(ctx):
    user_id = str(ctx.author.id)
    if not key_manager.has_claimed_key(user_id):
        await ctx.send("❌ You need to claim a key first using `!claim <key>`")
        return
    if user_id in config['active_sessions']:
        await ctx.send("⚠️ You already have an active session. Use `!stop` to stop it first.")
        return
    view = PanelView()
    await ctx.send(
        "📋 **Configuration Panel**\n\n"
        "Click the button below to open the configuration form.\n"
        "⚠️ This will open a popup in Discord!",
        view=view
    )

@bot.command(name='start')
async def start_bot(ctx):
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
    
    token_preview = settings['token'][:20] + '...'
    await ctx.send(f"⏳ **Starting bot...**\n"
                  f"Token: `{token_preview}`\n"
                  f"Channels: {len(settings['channel_ids'])}\n"
                  f"Interval: {settings['minutes']} minute(s)\n"
                  f"Bypass: {'ON' if settings.get('bypass', False) else 'OFF'}")
    
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
    await asyncio.sleep(3)
    if task.is_running:
        await ctx.send(f"✅ Bot started! Sending messages to {len(settings['channel_ids'])} channel(s) every {settings['minutes']} minute(s).")
        await logger.log_start_command(username)
    else:
        await ctx.send(
            f"❌ **Bot failed to start!**\n\n"
            f"**Common issues:**\n"
            f"• Invalid token (run `!panel` again with a fresh token)\n"
            f"• Token expired\n"
            f"• Account locked\n\n"
            f"Try: 1) Get fresh token  2) Run `!panel`  3) `!start` again"
        )
        if user_id in running_tasks:
            del running_tasks[user_id]

@bot.command(name='status')
async def status(ctx):
    user_id = str(ctx.author.id)
    if user_id in running_tasks and running_tasks[user_id].is_running:
        settings = config['panel_settings'].get(user_id, {})
        channel_count = len(settings.get('channel_ids', []))
        minutes = settings.get('minutes', 1)
        bypass = "ON" if settings.get('bypass', False) else "OFF"
        await ctx.send(f"🟢 **Bot Status**: Running\n📡 Channels: {channel_count}\n⏱️ Interval: {minutes} minute(s)\n🔄 Bypass: {bypass}")
        await logger.log_status_check(ctx.author.name, True)
    else:
        await ctx.send("🔴 **Bot Status**: Not running")
        await logger.log_status_check(ctx.author.name, False)

@bot.command(name='stop')
async def stop_bot(ctx):
    user_id = str(ctx.author.id)
    if user_id not in running_tasks:
        await ctx.send("❌ No active bot session found.")
        return
    task = running_tasks[user_id]
    if task.is_running:
        await task.stop()
        del running_tasks[user_id]
        await ctx.send("🛑 Bot stopped successfully!")
        await logger.log_stop_command(ctx.author.name)
    else:
        await ctx.send("❌ Bot is not running.")

# Notice: bypasson and bypassoff are already handled inside the MessageTask's on_message
# But we also want them available as global commands for when the bot is not running?
# Actually, the user can only toggle bypass when the bot is running (since the task handles it).
# If they want to toggle bypass without starting, they can use the global commands:
@bot.command(name='bypasson')
async def bypasson_global(ctx):
    user_id = str(ctx.author.id)
    if user_id not in config['panel_settings']:
        await ctx.send("❌ Please set up the bot first using `!panel`")
        return
    config['panel_settings'][user_id]['bypass'] = True
    save_config(config)
    if user_id in running_tasks:
        running_tasks[user_id].bypass_mode = True
    await ctx.send("🔄 Bypass mode is now **ON** – delays and retry logic active.")
    await logger.log_bypass(ctx.author.name, True)

@bot.command(name='bypassoff')
async def bypassoff_global(ctx):
    user_id = str(ctx.author.id)
    if user_id not in config['panel_settings']:
        await ctx.send("❌ Please set up the bot first using `!panel`")
        return
    config['panel_settings'][user_id]['bypass'] = False
    save_config(config)
    if user_id in running_tasks:
        running_tasks[user_id].bypass_mode = False
    await ctx.send("🔄 Bypass mode is now **OFF** – normal speed.")
    await logger.log_bypass(ctx.author.name, False)

@bot.command(name='help')
async def help_command(ctx):
    help_text = f"""
**🤖 Discord Self-Bot Commands:**

**🔒 Admin Only:**
`{bot.command_prefix}genkey <count>` - Generate keys (max 100)
`{bot.command_prefix}listkey` - List available keys

**👥 Public:**
`{bot.command_prefix}claim <key>` - Claim a key
`{bot.command_prefix}panel` - Open config panel
`{bot.command_prefix}start` - Start sending messages
`{bot.command_prefix}status` - Check running status
`{bot.command_prefix}stop` - Stop the bot
`{bot.command_prefix}bypasson` - Enable bypass (delays + retries)
`{bot.command_prefix}bypassoff` - Disable bypass
`{bot.command_prefix}test` - Test if bot responds
`{bot.command_prefix}ping` - Check latency
`{bot.command_prefix}help` - Show this

**Setup:**
1. Claim a key: `{bot.command_prefix}claim <key>`
2. Configure: `{bot.command_prefix}panel`
3. Start: `{bot.command_prefix}start`
4. (Optional) Enable bypass: `{bot.command_prefix}bypasson`

**⚠️ Self-bot – use at your own risk.**
"""
    await ctx.send(help_text)

# ============ ERROR HANDLER ============
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CheckFailure):
        await ctx.send("❌ **Access Denied!** Admin only.")
    elif isinstance(error, commands.CommandNotFound):
        await ctx.send(f"❌ Unknown command. Use `{bot.command_prefix}help`.")
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
        exit(1)
    try:
        bot.run(token)
    except discord.LoginFailure:
        print("❌ Invalid token.")
    except Exception as e:
        print(f"❌ Error: {e}")
