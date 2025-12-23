"""Green agent implementation - manages assessment and evaluation for Werewolf Game."""

import asyncio
import random
from typing import List, Optional
from uuid import uuid4

# Import the local WhiteAgent for NPC players
from ..white.player import Player
from .messenger import Messenger

DEFAULT_PLAYERS = [
    "Alice",
    "Bob",
    "Charlie",
    "David",
    "Eva",
    "Frank",
    "Grace",
    "Hannah",
    "Ian",
    "Judy",
]
MIN_GAME_SIZE = 6
CONVERSATION_ROUNDS = 3


class AsyncPlayer:
    def __init__(self, name, role, agent_url=None):
        self.messenger = Messenger()

        self.name = name
        self.role = role

        self.is_alive = True
        self.protected = False

        self.agent_url = agent_url
        self.is_remote = agent_url is not None

        self.agent = Player() if not self.is_remote else None

    def __repr__(self):
        status = "Alive" if self.is_alive else "Dead"
        remote_tag = "[Remote]" if self.is_remote else "[Local]"
        return f"{self.name} ({self.role}, {status}) {remote_tag}"

    def to_dict(self):
        return {
            "name": self.name,
            "role": self.role,
            "is_alive": self.is_alive,
            "is_remote": self.is_remote,
        }

    async def send(self, message: str, skip_response=False):
        if self.is_remote:
            # make A2A call to remote agent
            metadata = {"skip_response": skip_response}
            response = await self.messenger.talk_to_agent(
                message,
                url=self.agent_url,
                metadata=metadata,
            )

            return response
        else:
            # use local agent instance
            return await self.agent.handle(message, skip_response=skip_response)


class AsyncGameEnvironment:
    def __init__(self, participants: dict[str, str], config: dict = None):
        self.players: List[AsyncPlayer] = []
        self.werewolf: AsyncPlayer = None
        self.seer: AsyncPlayer = None
        self.medic: AsyncPlayer = None

        self.game_over = False
        self.winner: Optional[str] = None

        self.game_log: List[str] = []
        self.narration: List[str] = []

        self.participants = participants
        config = config or {}
        self.conv_rounds = config.get("conversation_rounds", CONVERSATION_ROUNDS)
        if self.conv_rounds < 1 or self.conv_rounds > 5:
            raise ValueError("conversation_rounds must be between 1 and 5.")
        self._assign_roles(participants, config.get("player_count", MIN_GAME_SIZE))

    def _assign_roles(self, participants: dict[str, str], player_count) -> None:
        """Assign roles to all players"""
        remote_count = len(participants)
        player_count = max(player_count, remote_count)
        if player_count > len(DEFAULT_PLAYERS):
            raise ValueError(
                f"Cannot support more than {len(DEFAULT_PLAYERS)} players."
            )
        npc_count = max(player_count - remote_count, 0)

        agent_names = list(participants.keys())
        agent_urls = list(participants[n] for n in agent_names)

        names = DEFAULT_PLAYERS[:player_count]
        names = agent_names + names[:npc_count]  # use provided names first
        roles = ["Werewolf", "Seer", "Medic"] + ["Villager"] * (player_count - 3)
        agent_urls = agent_urls + [None] * npc_count  # pad for local players

        random.shuffle(roles)

        for name, role, agent_url in zip(names, roles, agent_urls):
            player = AsyncPlayer(name, role, agent_url)
            self.players.append(player)
            if role == "Werewolf":
                self.werewolf = player
            elif role == "Seer":
                self.seer = player
            elif role == "Medic":
                self.medic = player

        print("--- Roles have been assigned secretly ---")
        for p in self.players:
            print(p)

    def check_game_over(self):
        living = [p for p in self.players if p.is_alive]
        num_wolves = len([p for p in living if p.role == "Werewolf"])
        num_others = len(living) - num_wolves
        if num_wolves == 0:
            self.game_over = True
            self.winner = "Villagers"
        elif num_wolves >= num_others:
            self.game_over = True
            self.winner = "Werewolves"

    def get_reports(self):
        reports = {
            p.name: {
                "role": p.role,
                "team_win": (self.winner == "Werewolves" and p.role == "Werewolf")
                or (self.winner == "Villagers" and p.role != "Werewolf"),
            }
            for p in self.players
        }
        for name in reports:
            reports[name]["suspicion_score"] = sum(
                1
                for log in self.game_log
                if log.startswith("VOTE:") and log.split(":")[2] == name
            )
        for voter in self.players:
            if voter.role != "Werewolf":
                votes = [
                    log
                    for log in self.game_log
                    if log.startswith(f"VOTE:{voter.name}:")
                ]
                if votes:
                    correct = sum(
                        1
                        for v in votes
                        if reports[v.split(":")[2]]["role"] == "Werewolf"
                    )
                    reports[voter.name]["voting_accuracy"] = correct / len(votes)
        return reports

    def run_evaluation(self):
        print("\n--- PERFORMANCE EVALUATION ---")
        reports = self.get_reports()
        for name, r in reports.items():
            print(f"\nPlayer: {name} ({r['role']})")
            print(f"  - Team Win: {'Yes' if r['team_win'] else 'No'}")
            print(f"  - Suspicion Score: {r['suspicion_score']}")
            if "voting_accuracy" in r:
                print(f"  - Voting Accuracy: {r['voting_accuracy']:.2f}")

    @property
    def alive_players(self):
        return [p for p in self.players if p.is_alive]

    async def _broadcast(self, message: str, skip_response=False):
        """Send a message to all players concurrently."""
        tasks = []
        for player in self.players:
            if player.is_alive:
                tasks.append(player.send(message, skip_response=skip_response))
        return await asyncio.gather(*tasks)

    def _parse_name(self, raw: str) -> Optional[AsyncPlayer]:
        """
        Identify player from player name.
        """
        clean = raw.strip().lower()
        for p in self.alive_players:
            if p.name.lower() in clean:
                return p
        return None

    def log(self, message: str = ""):
        self.narration.append(message)
        print(message)

    async def _phase_day_1(self):
        """
        Special handling for Day 1.
        - Players are informed of their roles.
        - Players concurrently generate an initial statement.
        """
        self.log("-" * 20)
        self.log(f"The sun rises upon Day 1 and the players introduce themselves.\n")

        # gather introductions
        async def _introduce(player: AsyncPlayer):
            other_players = ", ".join([p.name for p in self.players if p != player])
            role_message = (
                f"It is Day 1. Your name is {player.name} and your secret role is {player.role}.\n"
                f"The other players are: {other_players}.\n"
                "Make an opening statement to introduce yourself.\n"
            )
            statement = await player.send(role_message)
            return f'{player.name}: "{statement}"'

        introductions = await asyncio.gather(
            *[_introduce(p) for p in self.alive_players]
        )

        for intro in introductions:
            self.log(f">>> {intro}")

        # notify players of everyone elses introductions
        async def _notify_introductions(player: AsyncPlayer, idx: int):
            others_intro = "\n".join(
                [intro for i, intro in enumerate(introductions) if i != idx]
            )
            notify_message = (
                f"The other players introduce themselves as well.\n{others_intro}"
            )
            await player.send(notify_message, skip_response=True)

        await asyncio.gather(
            *[_notify_introductions(p, i) for i, p in enumerate(self.alive_players)]
        )

    async def _phase_night(self, day: int):
        """
        Conduct night phase.
        - Werewolves choose a target to kill.
        - Medic protects a player.
        - Seer inspects a player.
        - Apply night actions.
        - Players receive a night outcome summary.
        """
        prelude = f"The sun sets as we enter Night {day}.\n"
        self.log("-" * 20)
        self.log(prelude)

        # Werewolf picks target
        werewolf_target_raw = await self.werewolf.send(
            prelude + "Werewolf, who do you want to kill? Reply with ONLY the name."
        )
        werewolf_target = self._parse_name(werewolf_target_raw)
        if werewolf_target:
            self.log(
                f" 🐺 {self.werewolf.name} chooses to kill {werewolf_target.name}."
            )
        else:
            self.log(
                f" 🐺 {self.werewolf.name} tries to kill unknown `{werewolf_target_raw}`"
            )

        # Medic protects a player
        medic_target = None
        if self.medic.is_alive:
            medic_target_raw = await self.medic.send(
                prelude + "Medic, who do you want to protect? Reply with ONLY the name."
            )
            medic_target = self._parse_name(medic_target_raw)
            if medic_target:
                self.log(f" 💉 {self.medic.name} protects {medic_target.name}.")
                self.game_log.append(
                    f"MEDIC_PROTECTS:{self.medic.name}:{medic_target.name}"
                )
            else:
                self.log(
                    f" 💉 {self.medic.name} tries to protect unknown `{medic_target_raw}`"
                )

        # Seer inspects a player
        if self.seer.is_alive:
            seer_target_raw = await self.seer.send(
                prelude + "Seer, who do you want to inspect? Reply with ONLY the name."
            )
            seer_target = self._parse_name(seer_target_raw)
            if seer_target:
                seer_result = f"{seer_target.name} is a {seer_target.role}."
                self.log(
                    f" 👁️ {self.seer.name} inspects {seer_target.name} and learns that they are a {seer_target.role}."
                )
                self.game_log.append(
                    f"SEER_SEES:{self.seer.name}:{seer_target.name}:{seer_target.role}"
                )
            else:
                seer_result = "Your inspection yielded no results."
                self.log(
                    f" 👁️ {self.seer.name} tries to inspect unknown `{seer_target_raw}`"
                )
            await self.seer.send(f"{seer_result}", skip_response=True)

        self.log()
        if werewolf_target:
            if werewolf_target == medic_target:
                self.log(
                    f"🛡️ {werewolf_target.name} was targeted by the Werewolf but saved by the Medic."
                )
                self.game_log.append(f"SAVED:{werewolf_target.name}")
                night_summary = f"The Werewolf tried to kill {werewolf_target.name}, but they were saved by the Medic."
            else:
                self.log(f"☠️ {werewolf_target.name} was killed by the Werewolf.")
                self.game_log.append(
                    f"KILLED:{werewolf_target.name}:{werewolf_target.role}"
                )
                werewolf_target.is_alive = False
                night_summary = (
                    f"The Werewolf killed {werewolf_target.name} during the night."
                )
        else:
            night_summary = "No one was killed during the night."
            self.log(" No kills occurred during the night.")
        self.log()
        await self._broadcast(night_summary, skip_response=True)

    async def _phase_day(self, day: int):
        """
        Conduct day phase.
        - Players concurrently generate statements.
        - Players receive all statements and cast a vote.
        """
        self.log("-" * 20)
        self.log(f"The sun rises upon Day {day}.\n")

        # gather statements
        async def _speak(player: AsyncPlayer):
            role_message = (
                f"It is Day {day}.\n"
                "Make a statement to the other players. "
                "You can accuse someone, defend yourself, or try to guide the conversation.\n"
            )
            statement = await player.send(role_message)
            return f'{player.name}: "{statement}"'

        statements = await asyncio.gather(*[_speak(p) for p in self.alive_players])

        for stmt in statements:
            self.log(f">>> {stmt}")

        for i in range(self.conv_rounds - 1):
            # notify players of everyone elses statements
            async def _notify_statements(player: AsyncPlayer, idx: int):
                others_statements = "\n".join(
                    [stmt for i, stmt in enumerate(statements) if i != idx]
                )
                notify_message = (
                    f"The other players have made the following statements:\n"
                    f"{others_statements}\n\n"
                    f"You may make {'your final statement before voting.' if i == self.conv_rounds - 2 else 'another statement.'}"
                )
                new_statement = await player.send(notify_message)
                return f'{player.name}: "{new_statement}"'

            new_statements = await asyncio.gather(
                *[_notify_statements(p, i) for i, p in enumerate(self.alive_players)]
            )
            statements = new_statements

            for stmt in new_statements:
                self.log(f">>> {stmt}")

        self.log("\nThe players now vote to eliminate someone.\n")
        votes = {}

        # notify players of everyone elses statements and gather votes
        async def _vote(player: AsyncPlayer, idx: int):
            others_statements = "\n".join(
                [stmt for i, stmt in enumerate(statements) if i != idx]
            )
            vote_message = (
                f"The other players make the following statements:\n"
                f"{others_statements}\n\n"
                "Who do you want to eliminate? Reply with ONLY the name. If you don't want to eliminate anyone, reply with 'NONE'."
            )
            vote_raw = await player.send(vote_message)
            vote_target = self._parse_name(vote_raw)
            if vote_target:
                self.log(f" 🗳️ {player.name} votes to eliminate {vote_target.name}.")
                self.game_log.append(f"VOTE:{player.name}:{vote_target.name}")
                votes[vote_target.name] = votes.get(vote_target.name, 0) + 1

        await asyncio.gather(*[_vote(p, i) for i, p in enumerate(self.alive_players)])

        max_votes = max(votes.values())
        eliminated = [n for n, c in votes.items() if c == max_votes]

        if len(eliminated) == 1:
            name = eliminated[0]
            for p in self.players:
                if p.name == name:
                    p.is_alive = False
                    message = (
                        f"\nThe town has eliminated {p.name}. They were a {p.role}."
                    )
                    await self._broadcast(message, skip_response=True)
                    self.log(message)
                    self.game_log.append(f"ELIMINATED:{p.name}:{p.role}")
                    break
        else:
            message = f"\nThere was a tie between {', '.join(eliminated)}. No one is eliminated."
            self.log(message)
            await self._broadcast(message, skip_response=True)

    async def run_game(self):
        day = 1
        while not self.game_over:
            self.game_log.append(f"PHASE:{day}:DAY")
            if day == 1:
                await self._phase_day_1()
            else:
                await self._phase_day(day)
            self.check_game_over()
            if self.game_over:
                break

            self.game_log.append(f"PHASE:{day}:NIGHT")
            await self._phase_night(day)
            self.check_game_over()
            if self.game_over:
                break
            day += 1

        self.log("\n--- GAME OVER ---")
        self.log(f"The winner is: {self.winner}!")
        self.run_evaluation()
