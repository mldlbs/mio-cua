"""One-off: wrap the module-level run block of a scenario script in main().

The acceptance helpers need to be unit-testable, but the scripts were written
as flat top-to-bottom runners. Re-indenting 170 lines by hand invites a
whitespace typo, so it is done here instead.
"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

target = Path(sys.argv[1]).resolve()
marker = "# ── Run ──"

lines = target.read_text(encoding="utf-8").splitlines()
idx = next((i for i, l in enumerate(lines) if l.strip() == marker), None)
if idx is None:
    raise SystemExit(f"marker {marker!r} not found in {target}")

if any(l.startswith("def main(") for l in lines):
    raise SystemExit(f"{target.name} already has a main()")

body = []
for line in lines[idx + 1:]:
    body.append(("    " + line) if line.strip() else "")

out = lines[:idx + 1]
out += ["def main():"]
out += body
out += ["", "", 'if __name__ == "__main__":', "    main()"]

target.write_text("\n".join(out) + "\n", encoding="utf-8")
print(f"wrapped {len(body)} lines in main() -- {target}")
