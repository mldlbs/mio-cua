"""Guard against documentation drift in the MCP tool inventory.

The tool count had drifted three ways at once (README 36 / MCP.md 37 / code 38)
before 0.4.0. This test makes the drift impossible to merge: the code is the
single source of truth, and both docs must list exactly that set and declare
exactly that number.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MCP_SERVER = ROOT / "mio_cua" / "mcp_server.py"
README = ROOT / "README.md"
MCP_DOC = ROOT / "MCP.md"

#: Lowercase-only on purpose: env vars such as ``MIO_CUA_CONFIRM_OFF`` and
#: ``mio_cua_GPU`` must never be mistaken for tool names.
_TOOL_NAME = re.compile(r"`(mio_[a-z0-9_]+)`")


def tool_names_in_code() -> set:
    text = MCP_SERVER.read_text(encoding="utf-8")
    return set(re.findall(r'@mcp\.tool\(name="(mio_[a-z0-9_]+)"', text))


def tool_names_in_doc(path: Path) -> set:
    return set(_TOOL_NAME.findall(path.read_text(encoding="utf-8")))


def test_code_registers_tools():
    names = tool_names_in_code()
    assert len(names) >= 30, f"suspiciously few tools parsed from {MCP_SERVER.name}: {len(names)}"


def test_readme_lists_exactly_the_code_tools():
    code, doc = tool_names_in_code(), tool_names_in_doc(README)
    assert doc - code == set(), f"README lists tools that do not exist: {sorted(doc - code)}"
    assert code - doc == set(), f"README is missing tools: {sorted(code - doc)}"


def test_mcp_doc_lists_exactly_the_code_tools():
    code, doc = tool_names_in_code(), tool_names_in_doc(MCP_DOC)
    assert doc - code == set(), f"MCP.md lists tools that do not exist: {sorted(doc - code)}"
    assert code - doc == set(), f"MCP.md is missing tools: {sorted(code - doc)}"


def test_declared_counts_match_code():
    total = len(tool_names_in_code())
    readme = README.read_text(encoding="utf-8")
    mcp_doc = MCP_DOC.read_text(encoding="utf-8")

    declared = []
    declared += [int(n) for n in re.findall(r"\*\*(\d+)\*\*\s*个工具", readme)]
    declared += [int(n) for n in re.findall(r"工具分组表（共\s*(\d+)）", readme)]
    declared += [int(n) for n in re.findall(r"#\s*(\d+)\s*个 MCP 工具", readme)]
    declared += [int(n) for n in re.findall(r"上表共\s*\*\*(\d+)\*\*\s*个工具", mcp_doc)]

    assert declared, "no declared tool count found in README/MCP.md"
    assert all(n == total for n in declared), f"declared {declared}, code registers {total}"
