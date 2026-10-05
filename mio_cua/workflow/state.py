"""Workflow state and invariants.

Three invariants (enforced):
1. Discovery must be confirmed before Extraction.
2. Extraction must pass Validation before marked completed.
3. Validation failure must not overwrite original artifact.

App is Runtime context only; Core does not branch on app.
"""

from dataclasses import dataclass, field
from typing import List, Optional
import time


@dataclass
class Candidate:
    id: str
    name: str
    bbox: tuple = (0, 0, 0, 0)
    last_message_time: str = ""
    member_count: int = 0
    confidence: float = 0.0
    screenshot: str = ""
    observation_id: str = ""


@dataclass
class Record:
    timestamp: str
    sender: str
    content: str
    source: dict = field(default_factory=dict)  # {id, screenshot, observation_id, extraction_method}
    confidence: float = 1.0


@dataclass
class WorkflowState:
    task_id: str = ""
    app: str = ""  # Runtime context only
    keyword: str = ""
    candidates: List[Candidate] = field(default_factory=list)
    selected_ids: List[str] = field(default_factory=list)
    confirmed: bool = False
    confirmed_at: Optional[float] = None
    dataset: List[Record] = field(default_factory=list)
    validation: Optional[dict] = None
    artifacts: dict = field(default_factory=dict)  # stage -> path, immutable once set

    def confirm(self, selected_ids: List[str]):
        if not self.candidates:
            raise RuntimeError("Discovery must produce candidates before confirm")
        self.selected_ids = selected_ids
        self.confirmed = True
        self.confirmed_at = time.time()

    def assert_can_extract(self):
        if not self.confirmed or not self.selected_ids:
            raise RuntimeError("Discovery must be confirmed before Extraction (invariant 1)")

    def assert_can_complete(self):
        if self.validation is None or self.validation.get("status") != "passed":
            raise RuntimeError("Extraction must pass Validation before completed (invariant 2)")

    def set_artifact(self, stage: str, path: str, overwrite: bool = False):
        if stage in self.artifacts and not overwrite:
            # Validation failure must not overwrite original artifact (invariant 3)
            # caller should create new validation_result instead
            if stage == "extraction":
                raise RuntimeError("Validation failure must not overwrite original artifact")
        self.artifacts[stage] = path

    def set_validation(self, result: dict):
        # validation result is new artifact, never overwrites dataset
        self.validation = result
