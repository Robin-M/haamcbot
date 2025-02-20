import re
import datetime
import operator
from typing import List

import discord
from discord import ui, Guild
from discord.ext import commands
import mysql.connector
from discord.ext.commands import Context

import config

database = mysql.connector.connect(
    host=config.database['host'],
    user=config.database['user'],
    password=config.database['password'],
    database=config.database['name']
)


class SotwNominationModal(ui.Modal, title='Song of the week'):
    nomination_artist = ui.TextInput(label='Artist', custom_id='artist')
    nomination_title = ui.TextInput(label='Title', custom_id='title')
    nomination_anime = ui.TextInput(label='Anime', custom_id='anime')
    nomination_youtube = ui.TextInput(label='Youtube link', custom_id='youtube')

    async def on_submit(self, interaction: discord.Interaction):
        if not re.match(r'.*youtu\.?be.*', self.nomination_youtube.value):
            await interaction.response.send_message(f':x: Invalid youtube link', ephemeral=True)
            return
        message = f'{self.nomination_youtube.value}\n' \
                  f'**Artist:** {self.nomination_artist.value}\n' \
                  f'**Title:** {self.nomination_title.value}\n' \
                  f'**Anime:** {self.nomination_anime.value}\n' \
                  f'**User:** {interaction.user.mention}\n'
        channel = interaction.guild.get_channel_or_thread(config.channel['sotw'])
        message = await channel.send(message)
        await message.add_reaction('🔼')
        await interaction.response.send_message(f'Nomination added to {channel.mention}', ephemeral=True)


class SotwNomination(object):
    def __init__(self, message: discord.message):
        self.message = message
        try:
            self.votes = message.reactions[0].count - 1
        except IndexError:
            self.votes = 0

    def get_field_value(self, field):
        regex = rf"\*\*{field}\:\*\*([^\n]+)"
        content = self.message.content
        match = re.search(regex, content, re.IGNORECASE | re.MULTILINE)
        if match:
            return match.group(1).strip()
        else:
            return None

    def get_username(self):
        guild: Guild = self.message.guild
        return guild.get_member(self.get_userid()).display_name

    def get_userid(self):
        matches = re.search('<@([0-9]+)+>', self.message.content)
        return int(matches.group(1)) or None

    def get_youtube_code(self):
        regex = rf"([\w-]*)$"
        match = re.search(regex, self.message.content, re.IGNORECASE | re.MULTILINE)
        if match:
            return match.group(1)
        else:
            return None

    def get_yt_url(self):
        code = self.get_youtube_code()
        return f'https://www.youtube.com/watch?v={code}'

    def get_winner_text(self, week):
        return f"\nWeek {week}: {self.get_field_value('Artist')} - " \
               f"{self.get_field_value('Title')} ({self.get_field_value('Anime')}) " \
               f"door {self.get_username()} - {self.get_yt_url()}\n"

    def get_bbcode(self):
        yt_code = self.get_youtube_code()
        return f"[spoiler=\"{self.votes} Votes ({self.get_username()}) :" \
               f" {self.get_field_value('Artist')}" \
               f" - {self.get_field_value('Title')} ({self.get_field_value('Anime')})\"]" \
               f"[yt]{yt_code}[/yt]" \
               f"[/spoiler]\n"

    def get_ranking_text(self, i: int):
        return f":radio: {i + 1}) **{self.get_field_value('Artist')}** - " \
               f"**{self.get_field_value('Title')}**\n" \
               f"votes: **{self.votes}** | " \
               f"anime: *{self.get_field_value('Anime')}* | " \
               f"door: {self.get_username()}\n"


class Sotw(commands.Cog):
    # Init the command
    def __init__(self, bot):
        self.bot = bot

    # Get current week number except on a Sunday when it's the next week number
    @staticmethod
    def get_current_week_number():
        d = datetime.datetime.today()
        if d.weekday() == 6:
            d += datetime.timedelta(days=1)
        number = datetime.date(d.year, d.month, d.day).isocalendar()[1]
        return number

    # Get previous week number except on a Sunday when it's the current week number
    @staticmethod
    def get_previous_week_number():
        d = datetime.datetime.today()
        if d.weekday() != 6:
            d -= datetime.timedelta(days=7)
        number = datetime.date(d.year, d.month, d.day).isocalendar()[1]
        return number

    @commands.hybrid_group(name='sotw', invoke_without_commands=True, help='Song of the week')
    async def sotw(self, ctx):
        return

    async def get_ranked_nominations(self, ctx):
        user = ctx.message.author
        channel = next(ch for ch in user.guild.channels if ch.id == config.channel['sotw'])
        # Get history of channel since last message from the bot
        messages = [message async for message in channel.history(limit=100)]
        nominations = []
        for msg in messages:
            if msg.author.bot and re.match('.*Bij deze zijn de nominaties voor week.*', msg.content):
                break
            nominations.append(SotwNomination(msg))
        nominations.sort(key=operator.attrgetter('votes'), reverse=True)
        return nominations

    async def forum(self, nominations: List[SotwNomination]):
        msg = '```'
        msg += nominations[0].get_winner_text(self.get_previous_week_number())
        msg += '[spoiler]'
        for n in nominations:
            msg += n.get_bbcode()
        msg += f'[/spoiler]\n' \
               f'```\n' \
               f'<https://myanimelist.net/forum/?topicid=1680313>\n' \
               f'`t€scores add {nominations[0].get_userid()} 1500`\n' \
               f'<#{config.channel["sotw"]}>'
        return msg

    @sotw.command(pass_context=True, help='Show the SOTW ranking')
    async def ranking(self, ctx):
        nominations = await self.get_ranked_nominations(ctx)
        msg = ''
        for i, nomination in enumerate(nominations):
            msg += nomination.get_ranking_text(i)
        if msg == '':
            await ctx.send(':x: No nominations', ephemeral=True)
            return
        #await ctx.channel.send(msg)
        await ctx.send(f'Here is the current song of the week ranking\n{msg}', ephemeral=True)

    @sotw.command(pass_context=True, help='Announce the winner and start next round of SOTW')
    @commands.has_role(config.role['global_mod'])
    async def next(self, ctx: Context):
        print(f"user {ctx.author} started next song of the week round")
        database.reconnect()
        channel = ctx.guild.get_channel(config.channel['sotw'])
        nominations = await self.get_ranked_nominations(ctx)

        # Check if we have enough nominations and if we have a solid win
        if len(nominations) < 2:
            return await ctx.send(':x: Niet genoeg nominations', ephemeral=True)
        if nominations[0].votes == nominations[1].votes:
            return await ctx.send(':x: Het is een gelijke stand', ephemeral=True)

        # Build a dict of the winner for the win message and database insertion
        winner = nominations[0]
        await ctx.send(await self.forum(nominations))

        # Send the win message
        await channel.send(
            f":trophy: De winnaar van week {self.get_previous_week_number()} is: "
            f"{winner.get_field_value('Artist')} - "
            f"{winner.get_field_value('Title')} "
            f"({winner.get_field_value('Anime')}) "
            f"door <@{winner.get_userid()}> <{winner.get_yt_url()}>")

        # Send the start of the new nomination week
        await channel.send(
            f":musical_note: :musical_note: Bij deze zijn de nominaties voor week"
            f" {self.get_current_week_number()} geopend! :musical_note: :musical_note:\n"
            f"Gebruik `/sotw nomination` in een ander kanaal om te nomineren"
        )

        # Open database before sending win message
        sotw_cursor = database.cursor()

        # Construct sql
        sql = "INSERT INTO sotw_winner (member_id, artist, title, anime, youtube, created, votes, display_name)" \
              " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
        val = (
            winner.get_userid(),
            winner.get_field_value('Artist'),
            winner.get_field_value('Title'),
            winner.get_field_value('Anime'),
            winner.get_youtube_code(),
            datetime.datetime.now(),
            winner.votes,
            winner.get_username()
        )

        # Execute SQL
        sotw_cursor.execute(sql, val)

        # Commit change
        database.commit()

    @sotw.command(pass_context=True, help='Make a nomination for song of the week')
    @commands.has_role(config.role['user'])
    async def nomination(self, ctx: Context):
        await ctx.interaction.response.send_modal(SotwNominationModal())


async def setup(bot):
    await bot.add_cog(Sotw(bot))
