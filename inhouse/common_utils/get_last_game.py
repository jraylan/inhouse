from typing import Tuple, Optional

from inhouse.models import Game, GameParticipant


def get_last_game(
    player_id: int, server_id: int):
    games = Game.objects.filter(participants__player_id=player_id, server_id=server_id).order_by('-id')
    if games:
    	game = games[0]
    	participant = game.participants.filter(player_id=player_id)[0]
    	return games[0], participant
    return None, None
