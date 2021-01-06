from datetime import datetime, timedelta
from typing import List, Optional, Set
from psycopg2.errors import UniqueViolation

import sqlalchemy
from discord.ext import commands
from inhouse.exceptions .queue import *

from inhouse.common_utils.fields import roles_list

from inhouse.models import QueuePlayer, Player
from inhouse.common_utils.get_last_game import get_last_game
import logging




def is_in_ready_check(player_id) -> bool:
    return bool(
        QueuePlayer.objects.filter(player_id=player_id, ready_check_id__isnull=False)[:1]
    )


def reset_queue(channel_id: Optional[int] = None):
    """
    Resets queue in a specific channel.
    If channel_id is None, cancels *all* queues. Only for testing purposes.

    Args:
        channel_id: channel id of the queue to cancel
    """
    query = QueuePlayer.objects.all()

    if channel_id is not None:
        query = query.filter(channel_id=channel_id)

    query.delete()


def add_player(
    player_id: int, role: str, channel_id: int, server_id: int = None, name: str = None, jump_ahead=False
):
    # Just in case
    assert role in roles_list


    game, participant = get_last_game(player_id, server_id)

    if game and not game.winner:
        raise PlayerInGame

    # Then check if the player is in a ready-check
    if is_in_ready_check(player_id):
        raise PlayerInReadyCheck

    # This is where we add new Players to the server
    #   This is also useful to automatically update name changes
    player = Player()
    player.id = player_id
    player.server_id = server_id
    player.name = name
    player.save()

    # Finally, we actually add the player to the queue
    queue_time = datetime.now() if not jump_ahead else datetime.now() - timedelta(hours=24)
    queues = QueuePlayer.objects.filter(channel_id=channel_id, player_id=player_id,role=role)
    if queues:
        queues.update(queue_time=queue_time)
    else:
        queue_player = QueuePlayer()
        queue_player.channel_id = channel_id
        queue_player.player_id = player_id
        queue_player.role = role
        queue_player.queue_time = queue_time
        queue_player.save()

def remove_player(player_id: int, channel_id: int = None):
    """
    Removes the player from the queue in all roles in the channel

    If no channel id is given, drop him from *all* queues, cross-server
    """
    if (
        is_in_ready_check(player_id) and channel_id
    ):  # If we have no channel ID, it’s an !admin reset and we bypass the issue here
        raise PlayerInReadyCheck

    # We select the player’s rows
    query_player = QueuePlayer.objects.filter(player_id=player_id)

    # If given a channel ID (when the user calls !leave), we filter
    if channel_id:
        query_player = query_player.filter(channel_id=channel_id)

    query_player.delete()


def remove_players(player_ids: Set[int], channel_id: int):
    """
    Removes all players from the queue in all roles in the channel, without any checks
    """
    QueuePlayer.objects.filter(channel_id=channel_id, player_id__in=player_ids).delete()

def start_ready_check(player_ids: List[int], channel_id: int, ready_check_message_id: int):
    # Checking to make sure everything is fine
    assert len(player_ids) == 10

    QueuePlayer.objects.filter(channel_id=channel_id, player_id__in=player_ids).update(ready_check_id=ready_check_message_id)


def validate_ready_check(ready_check_id: int):
    """
    When a ready check is validated, we drop all players from all queues
    """
    QueuePlayer.objects.filter(ready_check_id=ready_check_id, player_id__in=player_ids).delete()

def cancel_ready_check(
    ready_check_id: int, ids_to_drop: Optional[List[int]], channel_id=None, server_id=None,
):
    """
    Cancels an ongoing ready check by reverting players to ready_check_id=None

    Drops players in ids_to_drop[]

    If server_id is not None, drops the player from all queues in the server
    """
    players_query = QueuePlayer.objects.filter(ready_check_id=ready_check_id).update(ready_check_id=None)
    logging.debug(f'Dropando ids {ids_to_drop}')
    if ids_to_drop:
        if server_id and channel_id:
            raise Exception("channel_id and server_id should not be used together here")

        players_query = QueuePlayer.objects.filter(player_id__in=ids_to_drop)
        duos_query = QueuePlayer.objects.filter(duo_id__in=ids_to_drop)
        # This removes the player from *all* queues in the server (timeout)
        if server_id:
            players_query = players_query.filter(channel__server_id=server_id)
            duos_query = duos_query.filter(channel__server_id=server_id)

        if channel_id:
            players_query = players_query.filter(channel_id=channel_id)
            duos_query = duos_query.filter(channel_id =channel_id)

        players_query.delete()
        duos_query.update(duo=None)

def cancel_all_ready_checks():
    """
    Cancels all ready checks, used when restarting the bot
    """
    QueuePlayer.objects.all().update(ready_check_id=None)


def get_active_queues() -> List[int]:
    """
    Returns a list of channel IDs where there is a queue ongoing
    """
    return [ r['channel_id'] for r in QueuePlayer.objects.all().values('channel_id')]


class PlayerInGame(Exception):
    ...


def add_duo(
    first_player_id: int,
    first_player_role: str,
    second_player_id: int,
    second_player_role: str,
    channel_id: int,
    server_id: int = None,
    first_player_name: str = None,
    second_player_name: str = None,
    jump_ahead=False,
):
    # Marks this group of players and roles as a duo

    if first_player_role == second_player_role:
        raise SameRolesForDuo

    # Just in case, we drop the players from the queue first
    remove_player(first_player_id, channel_id)
    remove_player(second_player_id, channel_id)

    add_player(
        player_id=first_player_id,
        role=first_player_role,
        channel_id=channel_id,
        server_id=server_id,
        name=first_player_name,
        jump_ahead=jump_ahead,
    )

    add_player(
        player_id=second_player_id,
        role=second_player_role,
        channel_id=channel_id,
        server_id=server_id,
        name=second_player_name,
        jump_ahead=jump_ahead,
    )

    first_queue_player = QueuePlayer.objects.get(
        player_id=first_player_id,
        role= first_player_role,
        channel_id=channel_id
    )

    second_queue_player = QueuePlayer.objects.get(
        player_id=second_player_id,
        role=second_player_role,
        channel_id=channel_id
    )

    logging.info(f'{first_queue_player}')
    logging.info(f'{second_queue_player}')


    first_queue_player.duo_id = second_queue_player.id
    second_queue_player.duo_id = first_queue_player.id
    first_queue_player.save()
    second_queue_player.save()


def remove_duo(player_id: int, channel_id: int):
    # Removes duos for all roles for this player in this channel
    # This could be called during a ready-check but it shouldn’t be too much of an issue
    QueuePlayer.objects.filter(player_id=player_id, channel_id=channel_id).update(duo_id=None)
    QueuePlayer.objects.filter(duo__player_id=player_id, channel_id=channel_id).update(duo_id=None)