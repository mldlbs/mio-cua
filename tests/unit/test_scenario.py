import yaml

from mio_cua.scenario import obs_to_scenario, scenario_to_yaml, load_scenario_yaml
from mio_cua.models.element import Element
from mio_cua.models.observation import Observation


def _els():
    return [
        Element(0, "merged", text="0", role="text", bbox=(400, 300, 240, 40)),
        Element(1, "merged", text="7", role="button", bbox=(400, 360, 50, 30)),
    ]


def test_scenario_to_yaml_roundtrip():
    els = _els()
    y = scenario_to_yaml(els, active_window="计算器", name="calc", source="merged")
    data = yaml.safe_load(y)
    assert data["name"] == "calc"
    assert data["active_window"] == "计算器"
    assert data["source"] == "merged"
    assert len(data["elements"]) == 2
    assert data["elements"][0] == {
        "id": 0, "text": "0", "role": "text",
        "bbox": [400, 300, 240, 40], "source": "merged",
    }


def test_obs_to_scenario_preserves_fields():
    obs = Observation(None, 1.0, "计算器", 1.0, _els())
    s = obs_to_scenario(obs, name="calc")
    assert s["active_window"] == "计算器"
    assert s["name"] == "calc"
    assert s["elements"][1]["text"] == "7"
    assert s["elements"][1]["bbox"] == [400, 360, 50, 30]
    assert s["elements"][1]["source"] == "merged"


def test_load_scenario_yaml_restores_observation(tmp_path):
    y = scenario_to_yaml(_els(), active_window="计算器", name="calc", source="merged")
    p = tmp_path / "scene.yaml"
    p.write_text(y, encoding="utf8")
    obs = load_scenario_yaml(str(p))
    assert obs.active_window == "计算器"
    assert len(obs.elements) == 2
    e = obs.elements[1]
    assert e.text == "7"
    assert e.role == "button"
    assert e.bbox == (400, 360, 50, 30)
    assert e.source == "merged"


def test_load_scenario_yaml_missing_active_window(tmp_path):
    p = tmp_path / "s.yaml"
    p.write_text("name: x\nelements: []\n", encoding="utf8")
    obs = load_scenario_yaml(str(p))
    assert obs.active_window == ""
    assert obs.elements == []


def test_load_scenario_yaml_missing_elements(tmp_path):
    p = tmp_path / "s.yaml"
    p.write_text("name: x\n", encoding="utf8")
    obs = load_scenario_yaml(str(p))
    assert obs.elements == []


def test_load_scenario_yaml_missing_file_raises(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        load_scenario_yaml(str(tmp_path / "nope.yaml"))


def test_load_scenario_yaml_non_mapping_raises(tmp_path):
    import pytest
    p = tmp_path / "s.yaml"
    p.write_text("- just\n- a\n- list\n", encoding="utf8")
    with pytest.raises(ValueError):
        load_scenario_yaml(str(p))


def test_load_scenario_yaml_bad_syntax_raises(tmp_path):
    import pytest
    p = tmp_path / "s.yaml"
    p.write_text("name: [unclosed\n", encoding="utf8")
    with pytest.raises(ValueError):
        load_scenario_yaml(str(p))
