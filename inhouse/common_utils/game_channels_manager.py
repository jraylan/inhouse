import logging
import asyncio

import discord
from discord import Embed
from discord.ext import tasks
from discord.ext import commands

from inhouse import game_queue
from inhouse.exceptions import *
from inhouse.models import ChannelInformation, QueuePlayer
from inhouse.common_utils.embeds import embeds_color
from inhouse.common_utils.emoji_and_thumbnails import get_role_emoji
from inhouse.common_utils.constants import PREFIX
from inhouse.queue_channel.matchmaker import MatchMaker
from django.dispatch import receiver
from django.core.cache import cache
from django.db.models.signals import post_save, pre_delete


class GameChannelManager:

    def __init__(self, bot):
        logging.info(f'starting GameChannelManager instance')
        self.bot = bot

        self.queue_channels = {}
        self._queue_cache = {}
        self.latest_queue_message_ids = {}

        self.match_makers = {}

        self.restart = True
        post_save.connect(self.add_queue, sender=QueuePlayer)
        pre_delete.connect(self.remove_queue, sender=QueuePlayer)

        post_save.connect(self.add_channel, sender=ChannelInformation)
        pre_delete.connect(self.remove_channel, sender=ChannelInformation)

    def fire_ready(self):
        logging.info(f'Iniciando as tasks do GameChannelManager')
        self.refresh_channel_queue.start()
        self.clear_unwanted_messages.start()

    async def create_game_channel(self, ctx, game):
        #if game.winner:
        #    return

        guild = ctx.guild
        category = await guild.create_category(f'Partida - {game.id}')
        text_channel = await guild.create_text_channel(f'{game.id}', category=category)
        blue_channel = await guild.create_voice_channel(f'🔵{game.id}', category=category)
        red_channel = await guild.create_voice_channel(f'🔴{game.id}', category=category)
        game.channel_category = category.id
        game.channel_text = text_channel.id
        game.channel_blue = blue_channel.id
        game.channel_red = red_channel.id
        game.save()

        teams = game.teams.BLUE

        #for t in teams.BLUE:


    async def delete_game_channel(self, ctx, game):
        #if game.winner:
        #    return
        
        guild = ctx.guild
        await guild.get_channel(game.channel_category).delete()
        await guild.get_channel(game.channel_text).delete()
        await guild.get_channel(game.channel_blue).delete()
        await guild.get_channel(game.channel_red).delete()

        participants = game.participants.all()

    def get_server_queues(self, channel_id):
        return [v for k,v in self.queue_channels[channel_id].items()]

    def add_matchmaker(self,channel_id):
        logging.info(f'Criando instancia do MatchMaker para o canal {channel_id}')
        self.match_makers[channel_id] = MatchMaker(channel_id, self)
        self.match_makers[channel_id].start()

    def remove_matchmaker(self,channel_id):
        logging.info(f'Remove instancia do MatchMaker para o canal {channel_id}')
        self.match_makers[channel_id].stop()
        self.match_makers.pop(channel_id, None)

    def add_queue(self, sender, instance, using,**kwargs):
        logging.warning('add_queue')
        self.queue_channels[instance.channel_id][instance.id] = instance

    def remove_queue(self, sender, instance, using,**kwargs):
        if self.queue_channels.get(instance.channel_id):
            self.queue_channels[instance.channel_id].pop(instance.id, None)

    def add_channel(self, sender, instance, using,**kwargs):
        logging.warning('add_queue')
        self.add_matchmaker(instance.id)
        self.queue_channels[instance.id] = {q.id:q for q in instance.queues.all()}

    def remove_channel(self, sender, instance, using,**kwargs):
        self.remove_matchmaker(instance.id)
        self.queue_channels.pop(instance.id, None)

    @tasks.loop(seconds=1, minutes=0, hours=0, count=None, reconnect=True)
    async def clear_unwanted_messages(self):
        guild = self.bot.guilds
        if not guild:
            return
        guild = guild[0]

        def check_msg(msg):
            if msg.author.bot:
                for embed in msg.embeds:
                    if embed.url == 'https://inhouse.local':
                        return False
            return True

        for channel_id in self.queue_channels:
            channel = guild.get_channel(channel_id)
            await channel.purge(check=check_msg)


    @tasks.loop(seconds=1, minutes=0, hours=0, count=None, reconnect=True)
    async def refresh_channel_queue(self):
        guild = self.bot.guilds

        if not guild:
            return

        guild = guild[0]
        if self.restart:
            channels = ChannelInformation.objects.filter(channel_type='QUEUE')
            for c in channels:
                self.add_matchmaker(c.id)
                self.queue_channels[c.id] = {q.id: q for q in c.queues.filter(ready_check_id__isnull=True).order_by('queue_time')}

        added_duo = []
        for channel_id in self.queue_channels:
            
            queue = game_queue.GameQueue(channel_id, [v for k,v in self.queue_channels[channel_id].items()])

            channel = guild.get_channel(channel_id)

            if not channel:
                logging.warning(f'Canal com o id {channel_id} não encontrado.')
                continue
            # If the new queue is the same as the cache, we simple return
            if queue == self._queue_cache.get(channel_id):
                return
            else:
                await channel.purge()

            # Else, we update our cache (useful to not send too many messages)
            self._queue_cache[channel.id] = queue

            # Create the queue embed
            embed = Embed(colour=embeds_color, url='https://inhouse.local')

            # Adding queue field
            queue_rows = []

            for role, role_queue in queue.queue_players_dict.items():
                queue_rows.append(
                    f"{get_role_emoji(role)} " + ", ".join(qp.player.short_name for qp in role_queue)
                )

            embed.add_field(name="Queue", value="\n".join(queue_rows))

            # Adding duos field if it’s not empty
            if queue.duos:
                duos_strings = []

                for duo in queue.duos:
                    if duo[0] in added_duo:
                        continue

                    duos_strings.append(
                        " + ".join(f"{qp.player.short_name} {get_role_emoji(qp.role)}" for qp in duo)
                    )
                    added_duo.append(duo[0])
                    added_duo.append(duo[1])

                embed.add_field(name="Duos", value="\n".join(duos_strings))

            embed.set_footer(
                text=f"Use {PREFIX}queue [role] para entrar em ou !leave para sair | Qualquer outra mensagen será deletada"
            )

            message_text = ""

            if self.restart:
                message_text += (
                    "\nO bot reiniciou e todos os jogadores na checagem foram colocados de volta na fila\n"
                    "O processo de matchmaking reiniciará quando alguem entrar ou mudar de fila."
                )

            # We save the message object in our local cache
            new_queue_message = await channel.send(message_text, embed=embed,)

            self.latest_queue_message_ids[channel.id] = new_queue_message.id
        self.restart = False


    def mark_queue_channel(self, channel_id, server_id):
        """
        Marks the given channel + server combo as a queue
        """
        channel = ChannelInformation(id=channel_id, server_id=server_id, channel_type="QUEUE")
        channel.save()

        logging.info(f"O canal {channel_id} foi marcado com uma fila")


    def unmark_queue_channel(self, channel_id, server_id):
        game_queue.reset_queue(channel_id)

        channel = ChannelInformation.objects.filter(id=channel_id, server_id=server_id, channel_type="QUEUE")
        if channel:
            channel.delete()
            logging.info(f"o canal {channel_id} foi marcado com uma canal comum.")
        logging.info(f"o canal {channel_id} não é uma fila.")


    def update_queue_channels(self, bot, server_id):
        """
        Updates the queues in the given server

        If the server is not specified (restart), updates queue in all tagged queue channels
        """
        if not server_id:
            restart = True
            channels_to_check = [k for k  in self.queue_channels.keys()]
        else:
            restart = False
            channels_to_check = self.get_server_queues(server_id)

        for channel_id in channels_to_check:
            channel = bot.get_channel(channel_id)

            if not channel:  # Happens when the channel does not exist anymore
                self.unmark_queue_channel(channel_id)  # We remove it for the future
                continue


def queue_channel_only():

    async def predicate(ctx):
        if ctx.channel.id not in ctx.bot.game_channels_manager.queue_channels:
            raise QueueChannelsOnly
        else:
            return True

    return commands.check(predicate)