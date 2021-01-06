
from discord.ext.commands import CheckFailure

class QueueChannelsOnly(CheckFailure):
	...

class PlayerInReadyCheck(CheckFailure):
    ...

class SameRolesForDuo(CheckFailure):
    ...
