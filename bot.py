import discord
from discord.ext import commands
import yt_dlp
import asyncio

# Setup intents
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Options for yt-dlp and FFmpeg
YDL_OPTIONS = {'format': 'bestaudio/best', 'noplaylist': 'True'}
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

@bot.event
async def on_ready():
    # Sync slash commands with Discord when the bot turns on
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Failed to sync commands: {e}")
    
    print(f'Bot is online as {bot.user}')

# Slash Command for /play
@bot.tree.command(name="play", description="Plays a song from YouTube in your voice channel")
async def play(interaction: discord.Interaction, search: str):
    # Defer response so Discord gives the bot time to search YouTube without timing out
    await interaction.response.defer()

    # Check if user is in a voice channel
    if not interaction.user.voice:
        await interaction.followup.send("You need to be in a voice channel to use this command!")
        return

    channel = interaction.user.voice.channel
    voice_client = interaction.guild.voice_client

    # Connect to voice if not already connected
    if voice_client is None:
        voice_client = await channel.connect()

    # Format YouTube search query
    if not search.startswith("http://") and not search.startswith("https://"):
        search_query = f"ytsearch:{search}"
    else:
        search_query = search

    # Extract audio stream with yt-dlp
    with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
        info = ydl.extract_info(search_query, download=False)
        if 'entries' in info:
            info = info['entries'][0]

        url2 = info['url']
        title = info.get('title', 'Audio')

    # Stream the audio using FFmpeg
    source = await discord.FFmpegOpusAudio.from_probe(url2, **FFMPEG_OPTIONS)
    voice_client.play(source)

    await interaction.followup.send(f"Now playing: **{title}**")

# Slash Command for /stop
@bot.tree.command(name="stop", description="Stops music and disconnects from voice channel")
async def stop(interaction: discord.Interaction):
    voice_client = interaction.guild.voice_client

    if voice_client:
        await voice_client.disconnect()
        await interaction.response.send_message("Disconnected from the voice channel.")
    else:
        await interaction.response.send_message("I'm not in a voice channel.")

import os
from dotenv import load_dotenv

load_dotenv()
bot.run(os.getenv("DISCORD_TOKEN"))