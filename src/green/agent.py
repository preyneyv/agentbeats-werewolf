import json
import re
from typing import Dict

from a2a.server.tasks import TaskUpdater
from a2a.types import DataPart, Message, Part, TaskState, TextPart
from a2a.utils import get_message_text, new_agent_text_message

from .environment import AsyncGameEnvironment


def parse_tags(str_with_tags: str) -> Dict[str, str]:
    """the target str contains tags in the format of <tag_name> ... </tag_name>, parse them out and return a dict"""

    tags = re.findall(r"<(.*?)>(.*?)</\1>", str_with_tags, re.DOTALL)
    result = {}
    for tag, content in tags:
        if tag not in result:
            result[tag] = []
        result[tag].append(content.strip())
    return result


class Agent:
    async def run(self, message: Message, updater: TaskUpdater) -> None:
        """Implement your agent logic here.

        Args:
            message: The incoming message
            updater: Report progress (update_status) and results (add_artifact)
        """
        input_text = get_message_text(message)
        data = json.loads(input_text)
        participants = data.get("participants", {})
        config = data.get("config", {})
        env = AsyncGameEnvironment(participants=participants, config=config)

        await updater.update_status(
            TaskState.working, new_agent_text_message("Running Werewolf simulation...")
        )
        await env.run_game()

        result = {
            "winner": env.winner,
            "reports": env.get_reports(),
            "narration": "\n".join(env.narration),
            "event_log": env.game_log,
            "players": [p.to_dict() for p in env.players],
        }

        result_emoji = "🐺" if env.winner == "Werewolves" else "🛖"
        player_summary = "\n".join(f" - {p}" for p in env.players)
        summary_msg = (
            f"Finished.\n"
            f"Winner: {result_emoji} {env.winner}\n"
            f"Players:\n{player_summary}\n"
        )

        await updater.add_artifact(
            parts=[
                Part(root=TextPart(text=summary_msg)),
                Part(root=DataPart(data=result)),
            ],
            name="Result",
        )
