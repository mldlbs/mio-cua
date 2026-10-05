from dataclasses import dataclass
from typing import Optional


@dataclass
class ToolContext:
    controller: object
    perception: object
    config: object
    events: object
    current_observation: object = None
    current_action_id: str = ""
    finished_status: str = ""
    finished_summary: str = ""
