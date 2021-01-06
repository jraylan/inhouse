import tempfile
from collections import defaultdict
from datetime import datetime, timedelta
from asgiref.sync import sync_to_async
import dateparser
import discord
import lol_id_tools
import mplcyberpunk
from django.db.models import Sum, Func, F

from discord import Embed
from discord.ext import commands, menus
from discord.ext.commands import guild_only
import matplotlib
import matplotlib.pyplot as plt

from inhouse.common_utils.constants import PREFIX
from inhouse.common_utils.docstring import doc
from inhouse.common_utils.emoji_and_thumbnails import get_role_emoji, get_rank_emoji
from inhouse.models import GameParticipant, Game, PlayerRating, Player
from inhouse.common_utils.fields import ChampionNameConverter, RoleConverter
from inhouse.common_utils.get_last_game import get_last_game

from inhouse.robot import InhouseBot
from inhouse.ranking_channel_handler.ranking_channel_handler import ranking_channel_handler
from inhouse.stats_menus.history_pages import HistoryPagesSource
from inhouse.stats_menus.ranking_pages import RankingPagesSource
import logging

logger = logging.getLogger("inhouse_bot")

matplotlib.use("Agg")
plt.style.use("cyberpunk")

roles_list = ["TOP", "JGL", "MID", "BOT", "SUP"]

class StatsCog(commands.Cog, name="Stats"):
    """
    Display game-related statistics
    """

    def __init__(self, bot: InhouseBot, role=None):
        self.bot = bot
        self.not_handles_ranking = bool(role and role != 'RANKING')

    @commands.command()
    @guild_only()
    @doc(f"""
        Saves the champion you used in your last game

        Older games can be filled with {PREFIX}champion champion_name game_id
        You can find the ID of the games you played with {PREFIX}history

        Example:
            {PREFIX}champion riven
            {PREFIX}champion riven 1
    """)
    async def champion(
        self, ctx: commands.Context, champion_name: ChampionNameConverter(), game_id: int = None
    ):
        if self.not_handles_ranking:
            return

        if not game_id:
            game, participant = get_last_game(player_id=ctx.author.id, server_id=ctx.guild.id)
        else:
            participant = GameParticipant.objects.filter(game__id=game_id, player_id=ctx.author.id)
            if not participant:
                await ctx.send(
                    f"Partida não encontrada"
                )
                return
            
            participant = participant[0]
            game = participant.game

            # We write down the champion
            participant.champion_id = champion_name
            participant.save()
            game_id = game.id

        await ctx.send(
            f"Champion for game {game_id} was set to "
            f"{lol_id_tools.get_name(champion_name, object_type='champion')} for {ctx.author.display_name}"
        )

    @commands.command(aliases=["match_history", "mh"])
    @doc(f"""
        Displays your games history

        Example:
            {PREFIX}history
    """)
    async def history(self, ctx: commands.Context):

        if self.not_handles_ranking:
            return
        # TODO LOW PRIO Add an @ user for admins
        game_participant_query = GameParticipant.objects.filter(player_id=ctx.author.id).order_by('game__start')

        # If we’re on a server, we only show games played on that server
        if ctx.guild:
            game_participant_query = game_participant_query.filter(game__server_id=ctx.guild.id)


        if not game_participant_query:
            await ctx.send(
                f"Nenhuma partida encontrada"
            )
            return

        game_participant_list = [(g.game.all()[0], g) for g in game_participant_query[:20]]

        pages = menus.MenuPages(
            source=HistoryPagesSource(
                game_participant_list,
                self.bot,
                player_name=ctx.author.display_name,
                is_dms=True if not ctx.guild else False,
            ),
            clear_reactions_after=True,
        )
        await pages.start(ctx)

    @commands.command(aliases=["mmr", "rank", "rating"])
    @doc(f"""
        Returns your rank, MMR, and games played

        Example:
            {PREFIX}rank
    """)
    async def stats(self, ctx: commands.Context):
        if self.not_handles_ranking:
            return

        rating_objects = PlayerRating.objects.filter(player_id=ctx.author.id)

        if ctx.guild:
            rating_objects = rating_objects.filter(player__server_id=ctx.guild.id)

        rows = []

        for role in roles_list:
            # TODO LOW PRIO Make that a subquery
            row = rating_objects.filter(
                role=role
            )
            if not row:
                continue

            row = row[0]

            rank = PlayerRating.objects.annotate(mmr=Func(F('trueskill_mu'),F('trueskill_sigma'), function='mmr'))
            rank = rank.filter(mmr__gt=row.mmr).exclude(player_id=ctx.author.id).count()

            rank_str = get_rank_emoji(rank)
            wins = row.wins.count()

            row_string = (
                f"{f'{self.bot.get_guild(row.player_server_id).name} ' if not ctx.guild else ''}"
                f"{get_role_emoji(row.role)} "
                f"{rank_str} "
                f"`{int(row.mmr)} MMR  "
                f"{wins}W {row.count-wins}L`"
            )

            rows.append(row_string)

        embed = Embed(title=f"Ranks do jogador {ctx.author.display_name}", description="\n".join(rows))

        await ctx.send(embed=embed)

    @commands.command(aliases=["rankings"])
    @guild_only()
    @doc(f"""
        Displays the top players on the server

        A role can be supplied to only display the ranking for this role

        Example:
            {PREFIX}ranking
            {PREFIX}ranking mid
    """)
    async def ranking(self, ctx: commands.Context, role: RoleConverter() = None):
        if self.not_handles_ranking:
            return

        ratings = ranking_channel_handler.get_server_ratings(ctx.guild.id, role=role)

        if not ratings:
            await ctx.send("No games played yet")
            return

        pages = menus.MenuPages(
            source=RankingPagesSource(
                ratings,
                embed_name_suffix=f"on {ctx.guild.name}{f' - {get_role_emoji(role)}' if role else ''}",
            ),
            clear_reactions_after=True,
        )
        await pages.start(ctx)

    @commands.command(aliases=["rating_history", "ratings_history"])
    async def mmr_history(self, ctx: commands.Context):
        if self.not_handles_ranking:
            return
        """
        Displays a graph of your MMR history over the past month
        """
        date_start = datetime.now() - timedelta(hours=24 * 30)
        participants = GameParticipant.objects.filter(player_id=ctx.author.id,game__start__gt=date_start)
        participants = participants.order_by('game__start')

        mmr_history = defaultdict(lambda: {"dates": [], "mmr": []})

        latest_role_mmr = {}

        for row in participants:
            mmr_history[row.role]["dates"].append(row.game.all()[0].start)
            mmr_history[row.role]["mmr"].append(row.mmr)

            latest_role_mmr[row.role] = row.mmr

        legend = []
        for role in mmr_history:
            # We add a data point at the current timestamp with the player’s current MMR
            mmr_history[role]["dates"].append(datetime.now())
            mmr_history[role]["mmr"].append(latest_role_mmr[role])

            plt.plot(mmr_history[role]["dates"], mmr_history[role]["mmr"])
            legend.append(role)

        plt.legend(legend)
        plt.title(f"Variação de MMR no ultimo mês - {ctx.author.display_name}")
        mplcyberpunk.add_glow_effects()

        # This looks to be unnecessary verbose with all the closing by hand, I should take a look
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temp:
            plt.savefig(temp.name)
            file = discord.File(temp.name, filename=temp.name)
            await ctx.send(file=file)
            plt.close()
            temp.close()

    # TODO MEDIUM PRIO (simple) Add !champions_stats once again!!!
