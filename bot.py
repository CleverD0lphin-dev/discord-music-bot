import os
import asyncio
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
import yt_dlp

# Load environment variables
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# Setup bot intents
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Per-guild music queues: { guild_id: [ {'title': str, 'url': str}, ... ] }
song_queues = {}

# yt-dlp configuration
YTDL_OPTIONS = {
    'format': 'bestaudio/best',
    'extractaudio': True,
    'audioformat': 'mp3',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
}

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn',
}

ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)

# Helper function to play the next song in the queue
def play_next_in_queue(guild, channel):
    guild_id = guild.id
    if guild_id in song_queues and len(song_queues[guild_id]) > 0:
        next_song = song_queues[guild_id].pop(0)
        voice_client = guild.voice_client

        if voice_client and voice_client.is_connected():
            raw_source = discord.FFmpegPCMAudio(next_song['url'], **FFMPEG_OPTIONS)
            audio_source = discord.PCMVolumeTransformer(raw_source, volume=1.0)
            
            # play next track and set recursion loop for subsequent songs
            voice_client.play(
                audio_source, 
                after=lambda e: play_next_in_queue(guild, channel)
            )

            # Send update message in text channel
            view = MusicControlView(voice_client)
            embed = discord.Embed(title="🎶 Now Playing", description=f"**{next_song['title']}**", color=discord.Color.blue())
            embed.add_field(name="Volume", value="🔊 100%", inline=True)
            
            coro = channel.send(embed=embed, view=view)
            asyncio.run_coroutine_threadsafe(coro, bot.loop)

# Interactive Control View with Dynamic Volume Display
class MusicControlView(discord.ui.View):
    def __init__(self, voice_client):
        super().__init__(timeout=None)
        self.vc = voice_client

    async def update_embed(self, interaction: discord.Interaction, note: str):
        current_vol = int(getattr(self.vc.source, 'volume', 1.0) * 100) if self.vc and self.vc.source else 100
        
        embed = discord.Embed(
            title="🎶 Playback Controls", 
            description=f"Status: **{note}**", 
            color=discord.Color.blue()
        )
        embed.add_field(name="Current Volume", value=f"🔊 {current_vol}%", inline=True)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Pause / Resume", style=discord.ButtonStyle.primary, emoji="⏯️")
    async def pause_resume_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.vc or not self.vc.is_connected():
            return await interaction.response.send_message("Not connected to a voice channel.", ephemeral=True)
        
        if self.vc.is_playing():
            self.vc.pause()
            await self.update_embed(interaction, "Paused ⏸️")
        elif self.vc.is_paused():
            self.vc.resume()
            await self.update_embed(interaction, "Resumed ▶️")
        else:
            await interaction.response.send_message("Nothing is playing.", ephemeral=True)

    @discord.ui.button(label="Skip", style=discord.ButtonStyle.secondary, emoji="⏭️")
    async def skip_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.vc and (self.vc.is_playing() or self.vc.is_paused()):
            self.vc.stop() # Stopping triggers the 'after' parameter to play the next queued song
            await interaction.response.send_message("⏭️ Skipped song.", ephemeral=True)
        else:
            await interaction.response.send_message("No song to skip.", ephemeral=True)

    @discord.ui.button(label="Vol -", style=discord.ButtonStyle.secondary, emoji="🔉")
    async def vol_down_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.vc and self.vc.source:
            current_vol = getattr(self.vc.source, 'volume', 1.0)
            new_vol = max(0.0, current_vol - 0.1)
            self.vc.source.volume = new_vol
            await self.update_embed(interaction, f"Volume decreased to {int(new_vol * 100)}%")
        else:
            await interaction.response.send_message("No active audio playing.", ephemeral=True)

    @discord.ui.button(label="Vol +", style=discord.ButtonStyle.secondary, emoji="🔊")
    async def vol_up_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.vc and self.vc.source:
            current_vol = getattr(self.vc.source, 'volume', 1.0)
            new_vol = min(2.0, current_vol + 0.1)
            self.vc.source.volume = new_vol
            await self.update_embed(interaction, f"Volume increased to {int(new_vol * 100)}%")
        else:
            await interaction.response.send_message("No active audio playing.", ephemeral=True)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name} (ID: {bot.user.id})")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s).")
    except Exception as e:
        print(f"Command sync failed: {e}")

# /play command
@bot.tree.command(name="play", description="Play or queue a track")
@app_commands.describe(search="Song title or YouTube URL")
async def play(interaction: discord.Interaction, search: str):
    await interaction.response.defer()

    if not interaction.user.voice:
        return await interaction.followup.send("You must be in a voice channel!")

    channel = interaction.user.voice.channel
    voice_client = interaction.guild.voice_client

    if not voice_client:
        voice_client = await channel.connect()
    elif voice_client.channel != channel:
        await voice_client.move_to(channel)

    loop = asyncio.get_event_loop()
    try:
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(search, download=False))
        if 'entries' in data:
            data = data['entries'][0]
        
        stream_url = data['url']
        title = data.get('title', 'Unknown Track')
    except Exception as e:
        return await interaction.followup.send(f"Error fetching audio: {e}")

    guild_id = interaction.guild.id
    if guild_id not in song_queues:
        song_queues[guild_id] = []

    # If already playing, add to queue
    if voice_client.is_playing() or voice_client.is_paused():
        song_queues[guild_id].append({'title': title, 'url': stream_url})
        queue_position = len(song_queues[guild_id])
        return await interaction.followup.send(f"📥 Added to queue at **#{queue_position}**: **{title}**")

    # If not playing, play immediately
    raw_source = discord.FFmpegPCMAudio(stream_url, **FFMPEG_OPTIONS)
    audio_source = discord.PCMVolumeTransformer(raw_source, volume=1.0)

    voice_client.play(
        audio_source, 
        after=lambda e: play_next_in_queue(interaction.guild, interaction.channel)
    )

    view = MusicControlView(voice_client)
    embed = discord.Embed(title="🎶 Now Playing", description=f"**{title}**", color=discord.Color.green())
    embed.add_field(name="Current Volume", value="🔊 100%", inline=True)
    
    await interaction.followup.send(embed=embed, view=view)

# /queue command to view current queue list
@bot.tree.command(name="queue", description="View the current song queue")
async def queue(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    if guild_id not in song_queues or len(song_queues[guild_id]) == 0:
        return await interaction.response.send_message("The queue is currently empty.", ephemeral=True)

    queue_list = "\n".join([f"**{i+1}.** {song['title']}" for i, song in enumerate(song_queues[guild_id])])
    embed = discord.Embed(title="📜 Up Next in Queue", description=queue_list, color=discord.Color.orange())
    await interaction.response.send_message(embed=embed)

# /stop command
@bot.tree.command(name="stop", description="Stop music, clear queue, and disconnect")
async def stop(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    if guild_id in song_queues:
        song_queues[guild_id].clear()

    voice_client = interaction.guild.voice_client
    if voice_client and voice_client.is_connected():
        await voice_client.disconnect()
        await interaction.response.send_message("Cleared queue and left the voice channel.")
    else:
        await interaction.response.send_message("Bot is not in a voice channel.", ephemeral=True)

if __name__ == "__main__":
    if TOKEN:
        bot.run(TOKEN)
    else:
        print("Error: DISCORD_TOKEN missing in .env file.")