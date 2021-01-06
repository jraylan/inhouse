import asyncio

import random
import logging
import itertools

import trueskill
import math

from discord.ext import tasks
from inhouse import game_queue
from typing import Optional, List
from inhouse.common_utils.fields import roles_list
from inhouse.models import Game, QueuePlayer
from inhouse.common_utils.get_last_game import get_last_game
from inhouse.common_utils.validation_dialog import checkmark_validation



class MatchMaker:

    def __init__(self, channel_id, manager):
        self.channel_id = channel_id
        self.manger = manager
        self.bot= manager.bot
        self.channel = self.bot.guilds[0].get_channel(channel_id)



    def start(self):
        logging.info(f'Iniciando Matchmaking do canal {self.channel_id}')
        self.matchmaking_logic_task.start()
        return self

    def stop(self):
        logging.info(f'Parando Matchmaking do canal {self.channel_id}')
        self.matchmaking_logic_task.stop()


    @tasks.loop(seconds=5, minutes=0, hours=0, count=None, reconnect=True)
    async def matchmaking_logic_task(self):
        """
        Runs the matchmaking logic in the channel defined by the context

        Should only be called inside guilds
        """
        queue = game_queue.GameQueue(self.channel_id, [v for k,v in self.manger.queue_channels[self.channel_id].items()])

        logging.debug(f'Procurando por jogo')
        game = find_best_game(queue)

        if not game:
            logging.debug(f'Nenhum game encontrado')
            return

        elif game and game.matchmaking_score < 0.2:
            logging.debug(f'Jogo encontrado')
            embed = game.get_embed(embed_type="GAME_FOUND", validated_players=[], bot=self.bot)

            # We notify the players and send the message
            ready_check_message = await self.channel.send(content=game.players_ping, embed=embed, delete_after=60 * 15)

            await ready_check_message.add_reaction("✅")
            await ready_check_message.add_reaction("❌")

            # We mark the ready check as ongoing (which will be used to the queue)
            game_queue.start_ready_check(
                player_ids=game.player_ids_list,
                channel_id=self.channel_id,
                ready_check_message_id=ready_check_message.id,
            )

            # We update the queue in all channels
            #await self.bot.game_channels_manager.update_queue_channels(bot=self.bot, server_id=self.bot.guilds[0].id)

            # And then we wait for the validation
            try:
                ready, players_to_drop = await checkmark_validation(
                    bot=self.bot,
                    message=ready_check_message,
                    validating_players_ids=game.player_ids_list,
                    validation_threshold=10,
                    game=game,
                )

            # We catch every error here to make sure it does not become blocking
            except Exception as e:
                self.bot.logger.error(e)
                game_queue.cancel_ready_check(
                    ready_check_id=ready_check_message.id,
                    ids_to_drop=game.player_ids_list,
                    server_id=self.channel.guild.id,
                )
                await self.channel.send(
                    embed=self.bot.embed(
                    "There was a bug with the ready-check message, all players have been dropped from queue\n"
                    "Please queue again to restart the process"),
                    delete_after=10
                )

                return

            if ready is True:
                # We drop all 10 players from the queue
                game_queue.validate_ready_check(ready_check_message.id)

                # We commit the game to the database (without a winner)
                game.save()

                self.bot.game_channels_manager.mark_queue_related_message(
                    await self.channel.send(embed=game.get_embed("GAME_ACCEPTED"),)
                )

            elif ready is False:
                game.delete()
                # We remove the player who cancelled
                game_queue.cancel_ready_check(
                    ready_check_id=ready_check_message.id,
                    ids_to_drop=players_to_drop,
                    channel_id=self.channel.id,
                )

                await self.channel.send(
                    embed=self.bot.embed(
                    f"A player cancelled the game and was removed from the queue\n"
                    f"All other players have been put back in the queue"),
                    delete_after=15
                )


            elif ready is None:
                game.delete()
                # We remove the timed out players from *all* channels (hence giving server id)
                game_queue.cancel_ready_check(
                    ready_check_id=ready_check_message.id,
                    ids_to_drop=players_to_drop,
                    server_id=self.channel.guild.id,
                )

                await self.channel.send(
                    embed=self.bot.embed(
                    "The check timed out and players who did not answer have been dropped from all queues"),
                    delete_after=15
                )


        elif game and game.matchmaking_score >= 0.2:
            # One side has over 70% predicted winrate, we do not start anything
            await self.channel.send(
                embed=self.bot.embed(
                f"The best match found had a side with a {(.5 + game.matchmaking_score)*100:.1f}%"
                f" predicted winrate and was not started"),
                delete_after=30
            )


def evaluate_game(game: Game) -> float:
    """
    Returns the expected win probability of the blue team over the red team
    """

    blue_team_ratings = [
        trueskill.Rating(mu=p.trueskill_mu, sigma=p.trueskill_sigma) for p in game.teams.BLUE
    ]
    red_team_ratings = [trueskill.Rating(mu=p.trueskill_mu, sigma=p.trueskill_sigma) for p in game.teams.RED]

    delta_mu = sum(r.mu for r in blue_team_ratings) - sum(r.mu for r in red_team_ratings)

    sum_sigma = sum(r.sigma ** 2 for r in itertools.chain(blue_team_ratings, red_team_ratings))

    size = len(blue_team_ratings) + len(red_team_ratings)

    denominator = math.sqrt(size * (trueskill.BETA * trueskill.BETA) + sum_sigma)

    ts = trueskill.global_env()

    return ts.cdf(float(delta_mu) / float(denominator))



def find_best_game(queue: game_queue.GameQueue, game_quality_threshold=0.1) -> Optional[Game]:
    # Do not do anything if there’s not at least 2 players in queue per role

    for role_queue in queue.queue_players_dict.values():
        if len(role_queue) < 2:
            return None

    # If we get there, we know there are at least 10 players in the queue
    # We start with the 10 players who have been in queue for the longest time

    logging.info(f"Matchmaking process started with the following queue:\n{queue}")

    best_game = None
    for players_threshold in range(10, len(queue) + 1):
        # The queue_players are already ordered the right way to take age into account in matchmaking
        #   We first try with the 10 first players, then 11, ...
        best_game = find_best_game_for_queue_players(queue.queue_players[:players_threshold])

        # We stop when we beat the game quality threshold (below 60% winrate for one side)
        if best_game and best_game.matchmaking_score < game_quality_threshold:
            return best_game

    return best_game


def find_best_game_for_queue_players(queue_players: List[QueuePlayer]) -> Game:
    """
    A sub function to allow us to iterate on QueuePlayers from oldest to newest
    """
    logging.info(f"Trying to find the best game for: {' | '.join(f'{qp}' for qp in queue_players)}")

    # Currently simply testing all permutations because it should be pretty lightweight
    # TODO LOW PRIO Spot mirrored team compositions (full blue/red -> red/blue) to not calculate them twice

    # This creates a list of possible 2-players permutations per role
    # We keep it as a list to make it easier to make a product on the values afterwards
    role_permutations = []  # list of tuples of 2-players permutations in the role

    # We iterate on each role (which will have 2 players or more) and create one list of permutations per role
    for role in roles_list:
        role_permutations.append(
            [
                queue_player
                for queue_player in itertools.permutations([qp for qp in queue_players if qp.role == role], 2)
            ]
        )

    # We do a very simple maximum search
    best_score = 1
    best_game = None

    # This generates all possible team compositions
    # The format is a list of 5 tuples with the blue and red player objects in the tuple
    for team_composition in itertools.product(*role_permutations):
        # We already shuffle blue/red as otherwise the first best composition is always chosen
        shuffle = bool(random.getrandbits(1))

        # bool(tuple_idx) == shuffle explanation:
        #   tuple_idx = 0 (BLUE) &  shuffle = False -> False == False   -> True     -> BLUE
        #   tuple_idx = 1 (RED)  &  shuffle = False -> False == True    -> False    -> RED
        #   tuple_idx = 0 (BLUE) &  shuffle = True  -> False == True    -> False    -> RED
        #   tuple_idx = 1 (RED)  &  shuffle = True  -> True == True     -> True     -> BLUE

        # We transform it to a more manageable dictionary of QueuePlayers
        # {(team, role)} = QueuePlayer
        queue_players_dict = {
            ("BLUE" if bool(tuple_idx) == shuffle else "RED", roles_list[role_idx]): queue_players_tuple[
                tuple_idx
            ]
            for role_idx, queue_players_tuple in enumerate(team_composition)
            for tuple_idx in (0, 1)
        }

        # We check that all 10 QueuePlayers are in the same team as their duos

        # TODO LOW PRIO This is super stupid *but* works well enough for easy situations
        #   This is very much in need of a rewrite
        duos_not_in_same_team = False
        for team_tuple, qp in queue_players_dict.items():
            if qp.duo_id is not None:
                try:
                    next(
                        duo_qp
                        for duo_team_tuple, duo_qp in queue_players_dict.items()
                        if duo_team_tuple[0] == team_tuple[0] and duo_qp.player_id == qp.duo_id
                    )
                except StopIteration:
                    duos_not_in_same_team = True
                    continue

        if duos_not_in_same_team:
            continue

        # We take the players from the queue players and make it a new dict to create our games objects
        players = {k: qp.player for k, qp in queue_players_dict.items()}

        # We check to make sure all 10 players are different
        if set(players.values()).__len__() != 10:
            continue
            
        logging.info(players)
        # We create a Game object for easier handling, and it will compute the matchmaking score
        game = Game.from_players(players)

        # Importantly, we do *not* add the game to the session, as that will be handled by the bot logic itself

        if game.matchmaking_score < best_score:
            logging.info(
                f"New best game found with {game.blue_expected_winrate*100:.2f} blue side expected winrate"
            )

            best_game = game
            best_score = game.matchmaking_score
            # If the game is seen as being below 51% winrate for one side, we simply stop there (helps with big lists)
            if best_score < 0.01:
                break

    return best_game




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
