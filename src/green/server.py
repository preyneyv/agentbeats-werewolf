import uvicorn
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentSkill,
)

from .executor import Executor


def start(host, port, card_url):
    skill = AgentSkill(
        id="host_assess_werewolf_game",
        name="Werewolf Assessment",
        description="Run the Werewolf evaluation by wrapping the white agent, collecting statements/votes, and scoring the result. The remote white agent is given a random role; the remaining five seats are filled by NPCs controlled by the green agent.",
        tags=[],
        examples=[
            """
Your task is to assess the agents located at:
<white_agent_url>
http://localhost:9010
</white_agent_url>
<white_agent_url>
http://localhost:9011
</white_agent_url>
<white_agent_url>
http://localhost:9012
</white_agent_url>
"""
        ],
    )

    agent_card = AgentCard(
        name="werewolf_green_agent",
        description="Assessment hosting agent for the Werewolf evaluation harness.",
        url=card_url or f"http://{host}:{port}/",
        version="0.1.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=False),
        skills=[skill],
    )

    request_handler = DefaultRequestHandler(
        agent_executor=Executor(),
        task_store=InMemoryTaskStore(),
    )
    server = A2AStarletteApplication(
        agent_card=agent_card,
        http_handler=request_handler,
    )
    uvicorn.run(server.build(), host=host, port=port)
