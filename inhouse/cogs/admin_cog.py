from typing import Union

import discord
from discord.ext import commands
from discord.ext.commands import guild_only

from inhouse import game_queue, matchmaking_logic
from inhouse import models
from inhouse.common_utils.constants import PREFIX
from inhouse.common_utils.docstring import doc
import inhouse.common_utils.game_channels_manager
from inhouse.common_utils.get_last_game import get_last_game
from inhouse.robot import InhouseBot
from inhouse.ranking_channel_handler.ranking_channel_handler import ranking_channel_handler


class AdminCog(commands.Cog, name="Admin"):
    """
    Reset queues and manages games
    """

    def __init__(self, bot: InhouseBot, role=None):
        self.bot = bot
        self.not_handles_queue = bool(role and role != 'QUEUE')
        self.not_handles_ranking = bool(role and role != 'RANKING')
        
    @commands.group(case_insensitive=True)
    @commands.has_permissions(administrator=True)
    @doc(f"Admin functions, use {PREFIX}help admin for a complete list")
    async def admin(self, ctx: commands.Context):
        if ctx.invoked_subcommand is None:
            await ctx.send(
                f"The accepted subcommands are "
                f"{', '.join([c.name for c in self.walk_commands() if type(c) == commands.Command])}"
            )
   
    @admin.command()
    async def reset(
        self, ctx: commands.Context, member_or_channel: Union[discord.Member, discord.TextChannel] = None
    ):
        """
        Resets the queue status for a channel or a player

        If no argument is given, resets the queue in the current channel
        """
        if self.not_handles_queue:
            return

        if not member_or_channel or type(member_or_channel) == discord.TextChannel:
            channel = ctx.channel if not member_or_channel else member_or_channel
            game_queue.reset_queue(channel.id)

            # TODO Find a way to cancel the ongoing ready-checks as they *will* bug out
            #   The current code organisation does not allow to do it easily, so maybe it’ll need some structure changes
            await ctx.send(f"Filas resetadas em {channel.name}")

        elif type(member_or_channel) == discord.Member:
            game_queue.remove_player(member_or_channel.id)
            await ctx.send(f"{member_or_channel.name} foi removido de todas as filas")

        await self.bot.game_channels_manager.update_queue_channels(bot=self.bot, server_id=ctx.guild.id)

    @admin.command()
    async def won(self, ctx: commands.Context, member: discord.Member):
        """
        Scores the user’s last game as a win and recomputes ratings based on it
        """
        # TODO LOW PRIO Make a function that recomputes *all* ratings to allow to re-score/delete/cancel any game
        if self.not_handles_ranking:
            return

        matchmaking_logic.score_game_from_winning_player(player_id=member.id, server_id=ctx.guild.id)
        await ranking_channel_handler.update_ranking_channels(self.bot, ctx.guild.id)

        await ctx.send(
            f"O ultimo jogo de {member.display_name}’ foi marcado como vitória para seu time "
            f"e as estatísticas foram atualizadas"
        )

    @admin.command()
    async def cancel(self, ctx: commands.Context, member: discord.Member):
        """
        Cancels the user’s ongoing game

        Only works if the game has not been scored yet
        """
        if self.not_handles_queue:
            return

        game, participant = get_last_game(player_id=member.id, server_id=ctx.guild.id)

        if not game:
            await ctx.send("Jogo não encontrado")

        if game.winner:
            await ctx.send("O jogo já foi contado como vitória.")
            return

        game.delete()

        await ctx.send(f" O jogo do {member.display_name} foi cancelado e excluido do banco de dados.")
        await self.bot.game_channels_manager.update_queue_channels(bot=self.bot, server_id=ctx.guild.id)

    @admin.command()
    @guild_only()
    async def mark(self, ctx: commands.Context, channel_type: str):
        """
        Marks the current channel as a queue or ranking channel
        """
        if channel_type.upper() == "QUEUE":
            if self.not_handles_queue:
                await ctx.send(f"Os valor aceitos para o comando {PREFIX}admin mark é RANKING.")
                return
            self.bot.game_channels_manager.mark_queue_channel(ctx.channel.id, ctx.guild.id)

            await ctx.send(f"Canal atual marcado com fila")

        elif channel_type.upper() == "RANKING":
            if self.not_handles_ranking:
                await ctx.send(f"Os valor aceitos para o comando {PREFIX}admin mark é QUEUE.")
                return
            ranking_channel_handler.mark_ranking_channel(channel_id=ctx.channel.id, server_id=ctx.guild.id)
            await ctx.send(f"Canal atual marcado como ranques")

        else:
            await ctx.send(f"Os valores aceitos para o comando {PREFIX}admin mark são QUEUE e RANKING.")

    @admin.command()
    @guild_only()
    async def unmark(self, ctx: commands.Context):
        """
        Reverts the current channel to "normal"
        """
        self.bot.game_channels_manager.unmark_queue_channel(ctx.channel.id, ctx.guild.id)
        ranking_channel_handler.unmark_ranking_channel(ctx.channel.id)

        await ctx.send(f"O canal atual foi revertido para um canal normal.")
