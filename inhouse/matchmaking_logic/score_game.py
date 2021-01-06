import trueskill

from inhouse.models import Game
from inhouse.common_utils.get_last_game import get_last_game


def update_trueskill(game: Game):
    """
    Updates the player’s rating based on the game’s result
    """
    blue_team_ratings = {
        participant.player.ratings.get(role=participant.role): trueskill.Rating(
            mu=float(participant.trueskill_mu), sigma=float(participant.trueskill_sigma)
        )
        for participant in game.teams.BLUE
    }

    red_team_ratings = {
        participant.player.ratings.get(role=participant.role): trueskill.Rating(
            mu=float(participant.trueskill_mu), sigma=float(participant.trueskill_sigma)
        )
        for participant in game.teams.RED
    }

    if game.winner == "BLUE":
        new_ratings = trueskill.rate([blue_team_ratings, red_team_ratings])
    else:
        new_ratings = trueskill.rate([red_team_ratings, blue_team_ratings])

    for ratings in new_ratings:
        for player_rating in ratings:
            # This is the PlayerRating object
            player_rating.trueskill_mu = ratings[player_rating].mu
            player_rating.trueskill_sigma = ratings[player_rating].sigma

            player_rating.save()


def score_game_from_winning_player(player_id: int, server_id: int):
    """
    Scores the last game of the player on the server as a *win*
    """
    game, participant = get_last_game(player_id, server_id)
    if game:
        game.winner = participant.side
        update_trueskill(game)
        game.save()

        # Commit will happen here
