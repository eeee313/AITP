import discord
import asyncio
from datetime import datetime

class Logger:
    def __init__(self, log_channel_id):
        self.log_channel_id = log_channel_id
        self.bot = None
    
    def set_bot(self, bot):
        """Set the bot instance for sending logs"""
        self.bot = bot
    
    async def send_log(self, message, color="default"):
        """Send a log message to the log channel"""
        if not self.bot:
            return
        
        try:
            channel = self.bot.get_channel(self.log_channel_id)
            if channel:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                emoji = {
                    "success": "✅",
                    "error": "❌",
                    "warning": "⚠️",
                    "info": "ℹ️",
                    "default": "📋"
                }.get(color, "📋")
                
                await channel.send(f"{emoji} `[{timestamp}]` {message}")
        except Exception as e:
            print(f"Logging error: {e}")
    
    async def log_key_generation(self, username, count):
        """Log key generation"""
        await self.send_log(f"**Key Generation** - User: `{username}` generated `{count}` key(s)", "success")
    
    async def log_key_claim(self, username, key):
        """Log key claim"""
        await self.send_log(f"**Key Claim** - User: `{username}` claimed key: `{key}`", "info")
    
    async def log_panel_setup(self, username):
        """Log panel setup"""
        await self.send_log(f"**Panel Setup** - User: `{username}` completed panel setup", "success")
    
    async def log_start_command(self, username):
        """Log start command"""
        await self.send_log(f"**Start Bot** - User: `{username}` started the bot", "success")
    
    async def log_stop_command(self, username):
        """Log stop command"""
        await self.send_log(f"**Stop Bot** - User: `{username}` stopped the bot", "warning")
    
    async def log_status_check(self, username, is_running):
        """Log status check"""
        status = "Running" if is_running else "Not Running"
        await self.send_log(f"**Status Check** - User: `{username}` - Status: `{status}`", "info")
    
    async def log_startup(self, username, channel_count, minutes):
        """Log bot startup"""
        await self.send_log(f"**Bot Started** - User: `{username}` - Channels: `{channel_count}` - Interval: `{minutes} min`", "success")
    
    async def log_stop(self, username):
        """Log bot stop"""
        await self.send_log(f"**Bot Stopped** - User: `{username}` stopped the bot", "warning")
    
    async def log_message_sent(self, username, channel_id, message_preview):
        """Log message sent"""
        await self.send_log(f"**Message Sent** - User: `{username}` - Channel: `{channel_id}` - Preview: `{message_preview}...`", "info")
    
    async def log_error(self, username, error_message):
        """Log error"""
        await self.send_log(f"**Error** - User: `{username}` - Error: `{error_message}`", "error")
    
    async def log_list_keys(self, username):
        """Log list keys command"""
        await self.send_log(f"**List Keys** - User: `{username}` listed available keys", "info")
