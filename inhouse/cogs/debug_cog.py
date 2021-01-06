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
from inhouse.models import Game
from inhouse.ranking_channel_handler.ranking_channel_handler import ranking_channel_handler


class DebugCog(commands.Cog, name="Debug"):
    """
    Reset queues and manages games
    """

    def __init__(self, bot: InhouseBot, role=None):
        self.bot = bot
        self.not_handles_queue = bool(role and role != 'QUEUE')
        self.not_handles_ranking = bool(role and role != 'RANKING')
        
    @commands.group(case_insensitive=True)
    @commands.has_permissions(administrator=True)
    @doc(f"Debug functions, use {PREFIX}help debug for a complete list")
    async def debug(self, ctx: commands.Context):
        if ctx.invoked_subcommand is None:
            await ctx.send(
                f"The accepted subcommands are "
                f"{', '.join([c.name for c in self.walk_commands() if type(c) == commands.Command])}"
            )

    @debug.command()
    async def channel(
        self, ctx: commands.Context, command: str, game_id: int
    ):
        game =  Game.objects.filter(id=game_id)
        if game and command == 'create':
            await self.bot.game_channels_manager.create_game_channel(ctx, game[0])
            return
        if game and command == 'delete':
            await self.bot.game_channels_manager.delete_game_channel(ctx, game[0])
            return
    
        await ctx.send(
            f"a sintaxe do comando é:\n"
            f"{PREFIX}debug channel (create|delete) ID_DO_JOGO"
        )