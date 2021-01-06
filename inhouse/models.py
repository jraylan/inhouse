# -*- coding: utf-8 -*-
from __future__ import unicode_literals
from django.conf import settings 
from django.contrib.postgres.fields import JSONField
from django.db import models
from django.utils import timezone
import re
from datetime import datetime
from typing import Optional, Union, Tuple, List, Set
from tabulate import tabulate
from dataclasses import dataclass
from discord import Embed
import logging
from inhouse.common_utils.emoji_and_thumbnails import * 


roles_list = ["TOP", "JGL", "MID", "BOT", "SUP"]


class Server(models.Model):
    id = models.BigAutoField(primary_key=True)

    class Meta:
        verbose_name = 'Servidor'
        verbose_name_plural = 'Servidores'


class ChannelInformation(models.Model):
    """Represents a channel used by the inhouse bot"""
    
    id = models.BigAutoField(primary_key=True)

    server = models.ForeignKey('Server', on_delete=models.CASCADE)

    channel_type = models.CharField('Tipo de Canal', max_length=200, choices=(('RANKING','RANKING'),('QUEUE','QUEUE')))

    def __repr__(self):
        return f"<ChannelInformation: {self.id} | {self.server_id}>"


class Game(models.Model):

    start = models.DateTimeField('Início')

    # Server the game was played from
    server = models.ForeignKey('Server', on_delete=models.CASCADE)

    # Predicted outcome before the game was played
    blue_expected_winrate = models.DecimalField('Blue-side Winrate Experado', decimal_places=4,max_digits=6, null=True)

    # Winner, updated at the end of the game
    winner = models.CharField('Vencedor', max_length=4, choices=(("BLUE","BLUE"), ("RED","RED")), blank=True, null=True, default='')

    channel_category = models.BigIntegerField('Categoria', null=True)
    channel_text = models.BigIntegerField('Texto', null=True)
    channel_blue = models.BigIntegerField('Blue-side', null=True)
    channel_red = models.BigIntegerField('Red-side', null=True)

    # We define teams only as properties as it should be easier to work with
    @property
    def teams(self):
        @dataclass

        class Teams:
            BLUE: List[GameParticipant]
            RED: List[GameParticipant]

        return Teams(
            BLUE=list(self.participants.filter(side='BLUE')),
            RED=list(self.participants.filter(side='RED')),
        )

    @property
    def matchmaking_score(self):
        if not self.blue_expected_winrate:
            from inhouse.queue_channel.matchmaker import evaluate_game
            self.start = datetime.now()
            evaluated_game = evaluate_game(self)
            logging.info(f'Game avaliado com o rating {evaluated_game}')
            self.blue_expected_winrate = evaluated_game
        return abs(0.5 - float(self.blue_expected_winrate))

    @property
    def player_ids_list(self):
        return [p.player_id for p in self.participants.all()]

    @property
    def players_ping(self) -> str:
        return f"||{' '.join([f'<@{discord_id}>' for discord_id in self.player_ids_list])}||\n"

    def __str__(self):
        return tabulate(
            {"BLUE": [p.short_name for p in self.teams.BLUE], "RED": [p.short_name for p in self.teams.BLUE]},
            headers="keys",
        )

    def get_embed(self, embed_type: str, validated_players: Optional[List[int]] = None, bot=None) -> Embed:
        if embed_type == "GAME_FOUND":
            embed = Embed(
                title="📢 Game found 📢",
                url="https://inhouse.local",
                description=f"Blue side expected winrate is {self.blue_expected_winrate * 100:.1f}%\n"
                "If you are ready to play, press ✅\n"
                "If you cannot play, press ❌\n"
                "The queue will timeout after a few minutes and AFK players will be automatically dropped from queue",
            )
        elif embed_type == "GAME_ACCEPTED":
            embed = Embed(
                title="📢 Game accepted 📢",
                url="https://inhouse.local",
                description=f"Game {self.id} has been validated and added to the database\n"
                f"Once the game has been played, one of the winners can score it with `!won`\n"
                f"If you wish to cancel the game, use `!cancel`",
            )
        else:
            raise ValueError

        # Not the prettiest piece of code but it works well
        for side in ("BLUE", "RED"):
            embed.add_field(
                name=side,
                value="\n".join(  # This adds one side as an inline field
                    [
                        f"{get_role_emoji(roles_list[idx])}"  # We start with the role emoji
                        + (  # Then add loading or ✅ if we are looking at a validation embed
                            ""
                            if embed_type != "GAME_FOUND"
                            else f" {get_champion_emoji('loading', bot)}"
                            if p.player_id not in validated_players
                            else " ✅"
                        )
                        + f" {p.short_name}"  # And finally add the player name
                        for idx, p in enumerate(getattr(self.teams, side))
                    ]
                ),
            )

        return embed

    @classmethod
    def from_players(cls, players):
        g = cls()
        g.start = datetime.now()
        saved = False
        for k,v in players.items():
            if not saved:
                g.server = v.server
                g.save()
            side = k[0]
            role = k[1]
            try:
                player_mmr = v.ratings.get(role=role)
            except:
                player_mmr = PlayerRating.new(v, role)

            gp = GameParticipant()
            gp.game = g
            gp.player = v
            gp.side = side
            gp.role = role
            gp.name = v.name
            gp.trueskill_mu = player_mmr.trueskill_mu
            gp.trueskill_sigma = player_mmr.trueskill_sigma
            gp.save()

        from inhouse.queue_channel.matchmaker import evaluate_game
        g.start = datetime.now()
        evaluated_game = evaluate_game(g)
        logging.info(f'Game avaliado com o rating {evaluated_game}')
        g.blue_expected_winrate = evaluated_game
        g.save()
        return g

    def save(self,*args, **kwargs):
        super().save(*args,**kwargs)


class GameParticipant(models.Model):
    game = models.ForeignKey('Game', on_delete=models.CASCADE, related_name='participants')
    side = models.CharField('Lado', max_length=4, choices=(("BLUE","BLUE"), ("RED","RED")), db_index=True)
    role = models.CharField('Role', max_length=4,choices=[(role,role) for role in roles_list], db_index=True)

    player = models.ForeignKey('Player', on_delete=models.CASCADE, related_name='games')
    
    @property
    def player_server_id(self):
        return self.player.server_id

    @property
    def player_rating(self):
        return self.player.ratings.filter(role=self.role)
    

    champion_id = models.PositiveIntegerField('Campeão', blank=True, null=True, db_index=True)

    # Name as it was recorded when the game was played
    name = models.CharField('Nome do Jogador', max_length=200)

    # Pre-game TrueSkill values
    trueskill_mu = models.DecimalField('trueskill_mu', decimal_places=4,max_digits=6, db_index=True)
    trueskill_sigma = models.DecimalField('trueskill_sigma', decimal_places=4,max_digits=6, db_index=True)

    # Conservative rating for MMR display
    @property
    def mmr(self):
        return 20 * (self.trueskill_mu - 3 * self.trueskill_sigma + 25)

    @property
    def short_name(self):
        return self.name[:15]


class Player(models.Model):
    id = models.BigAutoField(primary_key=True)
    server = models.ForeignKey('Server', on_delete=models.CASCADE)

    # Player nickname and team as defined by themselves
    name = models.CharField('Nome do Jogador', max_length=200)
    team = models.CharField('Nome do Time', max_length=200, blank=True, null=True)

    # ORM relationship to the GameParticipant table
    @property
    def participant_objects(self):
        return self.gameparticipant.all()

    @property
    def short_name(self):
        return self.name[:15]

    def __repr__(self):
        return f"<Player: {self.id} | {self.name}>"


class QueuePlayer(models.Model):

    channel = models.ForeignKey('ChannelInformation', on_delete=models.CASCADE, related_name='queues')

    role = models.CharField('Role', max_length=4, choices=[(role,role) for role in roles_list], db_index=True)

    # Saving both allows us to going to the Player table
    player = models.ForeignKey('Player', on_delete=models.CASCADE)

    @property
    def player_server_id(self):
        return self.player.player_server_id
    
    # Duo queue partner
    duo = models.ForeignKey("QueuePlayer", on_delete=models.SET_NULL, null=True, blank=True)

    # Queue start time to favor players who have been in queue longer
    queue_time = models.DateTimeField('Data de entrada na fila', db_index=True, default=datetime.now)

    # None if not in a ready_check, ID of the ready check message otherwise
    ready_check_id = models.BigIntegerField('Confirmação', null=True, blank=True, db_index=True)

    @property
    def channel_information(self):
        return self.channel
  
    def __str__(self):
        return f"{self.player.name} - {self.role}"

    def save(self,*args, **kwargs):
        super().save(*args,**kwargs)

    def delete(self, *args, **kwargs):
        if self.duo:
            self.duo.duo = None
            self.duo.save()
        super().delete(*args,**kwargs)

    class Meta:
        unique_together = (('channel','player','role'),)

class PlayerRating(models.Model):

    player = models.ForeignKey('Player', on_delete=models.CASCADE, related_name='ratings')
    role = models.CharField('Role', max_length=4, choices=[(role,role) for role in roles_list], db_index=True)
    trueskill_mu = models.DecimalField('trueskill_mu', default=25, decimal_places=4,max_digits=6, db_index=True)
    trueskill_sigma = models.DecimalField('trueskill_sigma', default=25/3, decimal_places=4,max_digits=6, db_index=True)
    
    @property
    def wins(self):
        return self.player.games.filter(game__winner=models.F('side'), role=self.role)

    @property
    def count(self):
        return self.player.games.filter(role=self.role).count()
    
    @property
    def player_server_id(self):
        return self.player.player_server_id
    # Conservative rating for MMR display

    @property
    def mmr(self):
        return 20 * (self.trueskill_mu - 3 * self.trueskill_sigma + 25)

    @classmethod
    def new(cls, player, role):
        r = cls()
        r.player = player
        r.role = role
        r.trueskill_mu = 25
        r.trueskill_sigma = 25/3
        r.save()
        return r

    def __repr__(self):
        return f"<PlayerRating: player_id={self.player_id} role={self.role}>"

    class Meta:
        unique_together = ('player', 'role')