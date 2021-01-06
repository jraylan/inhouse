import logging
import os

import discord
from discord.ext import commands


from discord.ext.commands import NoPrivateMessage

from inhouse import game_queue
from inhouse.common_utils.constants import PREFIX
from inhouse.common_utils.game_channels_manager import GameChannelManager

from inhouse.exceptions import *
from discord import Embed

# Defining intents to get full members list
from inhouse.ranking_channel_handler.ranking_channel_handler import ranking_channel_handler

intents = discord.Intents.default()
intents.members = True

import traceback

class InhouseBot(commands.Bot):
    """
    A bot handling role-based matchmaking for LoL games
    """

    def __init__(self, **options):
        role = options.pop('role', None)
        super().__init__(PREFIX, intents=intents, case_insensitive=True, **options)

        # Importing locally to allow InhouseBot to be imported in the cogs
        from inhouse.cogs.queue_cog import QueueCog
        from inhouse.cogs.admin_cog import AdminCog
        from inhouse.cogs.stats_cog import StatsCog
        from inhouse.cogs.debug_cog import DebugCog
        self.add_cog(AdminCog(self, role=role))
        self.add_cog(QueueCog(self, role=role))
        self.add_cog(StatsCog(self, role=role))
        self.add_cog(DebugCog(self, role=role))
        self.embed = lambda x: Embed(url="https://inhouse.local", description=x)
        self.game_channels_manager = GameChannelManager(self)
        # Setting up some basic logging
        self.logger = logging.getLogger("inhouse_bot")

        self.add_listener(func=self.command_logging, name="on_command")

        # While I hate mixing production and testing code, this is the most convenient solution to test the bot
        if os.environ.get("INHOUSE_BOT_TEST"):
            from tests.test_cog import TestCog

            self.add_cog(TestCog(self))

    def run(self, *args, **kwargs):
        super().run(os.environ["INHOUSE_BOT_TOKEN"], *args, **kwargs)

    async def command_logging(self, ctx: discord.ext.commands.Context):
        """
        Listener called on command-trigger messages to add some logging
        """
        self.logger.info(f"{ctx.message.content}\t{ctx.author.name}\t{ctx.guild.name}\t{ctx.channel.name}")

    async def on_ready(self):
        self.logger.info(f"{self.user.name} has connected to Discord")

        game_queue.cancel_all_ready_checks()
        self.game_channels_manager.fire_ready()
        await ranking_channel_handler.update_ranking_channels(bot=self, server_id=None)

    async def __on_command_error(self, ctx, error):
        """
        Custom error command that catches CommandNotFound as well as MissingRequiredArgument for readable feedback
        """
        if isinstance(error, commands.CommandNotFound):
            await ctx.send(f"Command `{ctx.invoked_with}` not found, use {PREFIX}help to see the commands list")

        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"Arguments missing, use `{PREFIX}help {ctx.invoked_with}` to see the arguments list")

        elif isinstance(error, commands.ConversionError):
            # Conversion errors feedback are handled in my converters
            pass

        elif isinstance(error, NoPrivateMessage):
            await ctx.send(f"This command can only be used inside a server")

        elif isinstance(error, QueueChannelsOnly):
            await ctx.send(f"This command can only be used in a channel marked as a queue by an admin")

        elif isinstance(error, SameRolesForDuo):
            await ctx.send(f"Duos must have different roles")

        # This handles errors that happen during a command
        elif isinstance(error, commands.CommandInvokeError):
            og_error = error.original

            if isinstance(og_error, game_queue.PlayerInGame):
                await ctx.send(
                    delete_after=5,
                    embed=self.embed(
                    f"Your last game was not scored and you are not allowed to queue at the moment\n"
                    f"One of the winners can score the game with `{PREFIX}won`, "
                    f"or players can agree to cancel it with `{PREFIX}cancel`")
                )

            elif isinstance(og_error, game_queue.PlayerInReadyCheck):
                await ctx.send(
                    delete_after=5,
                    embed=self.embed(
                    f"A game has already been found for you and you cannot queue until it is accepted or cancelled\n"
                    f"If it is a bug, contact an admin and ask them to use `{PREFIX}admin reset` with your name")
                )

            else:
                # User-facing error
                await ctx.send(
                    delete_after=5,
                    embed=self.embed(
                    f"There was an error processing the command\n"
                    f"Use {PREFIX}help for the commands list or contact server admins for bugs")
                )

                self.logger.error(og_error)

        else:
            # User-facing error
            await ctx.send(
                delete_after=5,
                embed=self.embed(
                f"There was an error processing the command\n"
                f"Use {PREFIX}help for the commands list or contact server admins for bugs")
            )

        self.logger.error(f'Error Capturado')
        self.logger.error(error)
        self.logger.error(f'{traceback.format_exc()}')
        self.logger.error(f'{traceback.print_stack()}')