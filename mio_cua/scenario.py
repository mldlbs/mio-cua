"""Screenshot-to-YAML scenario conversion.

Turns a real desktop observation (or a screenshot's OCR output) into a YAML
scenario -- a static element list -- that the agent loop can replay offline
(``mio-cua run --simulate-scenario <scene.yaml>``) with no real input.
"""

import os

import yaml

from mio_cua.models.element import Element
from mio_cua.models.observation import Observation


def obs_to_scenario(obs, name="") -> dict:
    """Observation -> scenario dict (id/text/role/bbox/source per element)."""
    elements = []
    for e in obs.elements:
        elements.append({
            "id": e.id,
            "text": e.text or "",
            "role": e.role or "unknown",
            "bbox": [int(v) for v in e.bbox],
            "source": e.source or "merged",
        })
    return {
        "name": name,
        "active_window": getattr(obs, "active_window", "") or "",
        "source": "merged",
        "elements": elements,
    }


def scenario_to_yaml(elements, active_window="", name="", source="") -> str:
    """Element list + metadata -> YAML string."""
    elist = []
    for e in elements:
        item = {
            "id": e.id,
            "text": e.text or "",
            "role": e.role or "unknown",
            "bbox": [int(v) for v in e.bbox],
            "source": getattr(e, "source", None) or source or "merged",
        }
        elist.append(item)
    data = {
        "name": name,
        "active_window": active_window or "",
        "source": source or "merged",
        "elements": elist,
    }
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)


def load_scenario_yaml(path) -> Observation:
    """Load a scenario YAML file into an Observation (for replay).

    Raises ValueError with a friendly message if the file is missing or the
    YAML is malformed / not a mapping.
    """
    if not os.path.isfile(path):
        raise ValueError(f"scenario file not found: {path}")
    try:
        with open(path, "r", encoding="utf8") as f:
            data = yaml.safe_load(f)
    except Exception as e:
        raise ValueError(f"invalid scenario YAML in {path}: {e}") from e
    if not isinstance(data, dict):
        raise ValueError(f"invalid scenario YAML in {path}: expected a mapping, got {type(data).__name__}")
    elements = []
    for item in data.get("elements") or []:
        if not isinstance(item, dict):
            continue
        source = item.get("source") or data.get("source") or "merged"
        bbox = tuple(int(v) for v in (item.get("bbox") or [0, 0, 0, 0]))
        elements.append(Element(
            id=int(item.get("id") or 0),
            source=source,
            text=item.get("text") or "",
            role=item.get("role") or "unknown",
            bbox=bbox,
        ))
    return Observation(
        screenshot_path=None,
        timestamp=1.0,
        active_window=data.get("active_window") or "",
        dpi_scale=1.0,
        elements=elements,
    )
