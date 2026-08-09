from mio_cua.automation.backends import Backend, SendInputBackend
from mio_cua.models.action import Action
from mio_cua.models.action_result import RawResult


class InputController:
    """Resolves element references to coordinates, then delegates to a Backend."""

    def __init__(self, backend: Backend = None):
        self.backend = backend or SendInputBackend()
        self.current_observation = None

    def resolve(self, action: Action):
        """Replace element_id with the center coordinates from the current observation.

        If the action already carries explicit x/y, no resolution is needed. Raises
        if an element_id cannot be located, so the caller can treat it as retryable.
        """
        element_id = action.params.get("element_id")
        if element_id is None:
            return
        if action.params.get("x") is not None and action.params.get("y") is not None:
            return
        if self.current_observation is None:
            raise RuntimeError("element_id unresolved: no observation available to resolve against")
        for e in self.current_observation.elements:
            if e.id == element_id or str(e.id) == str(element_id):
                left, top, width, height = e.bbox
                action.params["x"] = int(left + width / 2)
                action.params["y"] = int(top + height / 2)
                action.params.pop("element_id", None)
                return
        # Fall back to scene nodes (e.g. OmniParser web controls whose ids live
        # above the merged-element range).
        scene = getattr(self.current_observation, "scene", None)
        if scene is not None:
            for n in getattr(scene, "nodes", []) or []:
                if n.id == element_id or str(n.id) == str(element_id):
                    left, top, width, height = n.bbox
                    action.params["x"] = int(left + width / 2)
                    action.params["y"] = int(top + height / 2)
                    action.params.pop("element_id", None)
                    return
        raise RuntimeError(f"element_id {element_id!r} not found in current observation")

    def execute(self, action: Action) -> RawResult:
        self.resolve(action)
        return self.backend.execute(action)
