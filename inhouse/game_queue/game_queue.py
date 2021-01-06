from collections import defaultdict
from typing import Dict, List, Tuple

from inhouse.models import QueuePlayer, PlayerRating
from inhouse.common_utils.fields import roles_list
from django.core.cache import cache


class GameQueue:
    """
    Represents the current queue state in a given channel
    """

    queue_players: List[QueuePlayer]

    def __init__(self, channel_id: int, potential_queue_players=None):

        if potential_queue_players == None:
            potential_queue_players = QueuePlayer.objects.filter(channel_id=channel_id,
                                                                ready_check_id__isnull=True).order_by('queue_time')

        # If we have no player in queue, we stop there
        if not potential_queue_players:
            self.server_id = None
            self.queue_players = []
            return
        # Else, we have our server_id from the players themselves
        else:
            for p in potential_queue_players[:1]:
                self.server_id = p.player.server_id
        
        if isinstance(potential_queue_players, list):
            self.queue_players = potential_queue_players
        else:
            self.queue_players = potential_queue_players.filter(player__server_id=self.server_id)

        for queue_player in self.queue_players:
            try:
                assert queue_player.player.ratings.get(role=queue_player.role)
            except PlayerRating.DoesNotExist:
                # If not, we create a new rating object
                PlayerRating.new(
                    queue_player.player, queue_player.role
                )

        # The starting queue is made of the 2 players per role who have been in queue the longest
        #   We also add any duos *required* for the game to fire
        starting_queue = defaultdict(list)

        for role in self.queue_players_dict:
            for qp in self.queue_players_dict[role]:

                # If we already have 2 players in that role, we continue
                if len(starting_queue[role]) >= 2:
                    continue

                # Else we add our current player if he’s not there yet (could have been added by his duo)
                # TODO LOW PRIO cleanup that ugly code
                if not filter(lambda x: x.player_id == qp.player_id, starting_queue[role]):
                    starting_queue[role].append(qp)

                # If he has a duo, we add it if he’s not in queue for his role already
                if qp.duo_id is not None:
                    duo_role = qp.duo.role

                    # We add the duo as part of the queue for his role *if he’s not yet in it*
                    # TODO LOW PRIO find a more readable syntax, all those list comprehensions are really bad
                    if not filter(lambda x: x.player_id == qp.duo_id , starting_queue[duo_role]):
                        if len(starting_queue[duo_role]) >= 2:
                            starting_queue[duo_role].pop()
                        starting_queue[duo_role].append(qp.duo)

        # Afterwards we fill the rest of the queue with players in chronological order

        age_sorted_queue_players = sum(
            list(starting_queue.values()), []
        )  # Flattening the QueuePlayer objects to a single list

        # This should always be the first game we try
        assert len(age_sorted_queue_players) <= 10

        # We create a (role, id) list to see who is already in queue more easily
        #   Simple equality does not work because the qp.duo objects are != from the solo qp objects
        age_sorted_queue_players_ids = [(qp.player_id, qp.role) for qp in age_sorted_queue_players]

        age_sorted_queue_players += [
            qp for qp in self.queue_players if (qp.player_id, qp.role) not in age_sorted_queue_players_ids
        ]

        self.queue_players = age_sorted_queue_players

    def __len__(self):
        return len(self.queue_players)

    def __eq__(self, other):
        if type(other) != GameQueue:
            return False

        simple_queue = [(qp.player_id, qp.role) for qp in self.queue_players]
        simple_other_queue = [(qp.player_id, qp.role) for qp in other.queue_players]

        return simple_queue == simple_other_queue

    def __str__(self):
        rows = []

        for role in roles_list:
            rows.append(
                f"{role}\t" + " ".join(qp.player.name for qp in self.queue_players if qp.role == role)
            )

        duos_strings = []
        for duo in self.duos:
            duos_strings.append(" + ".join(f"{qp.player.name} {qp.role}" for qp in duo))

        rows.append(f"DUO\t{', '.join(duos_strings)}")

        return "\n".join(rows)

    @property
    def queue_players_dict(self) -> Dict[str, List[QueuePlayer]]:
        """
        This dictionary will always have all roles included
        """
        return {role: [player for player in self.queue_players if player.role == role] for role in roles_list}

    @property
    def duos(self) -> List[Tuple[QueuePlayer, QueuePlayer]]:
        return [(qp, qp.duo) for qp in filter(lambda x: bool(x.duo), self.queue_players)]
