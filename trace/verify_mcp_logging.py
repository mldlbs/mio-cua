"""Verify MCP logging: file + stderr, no stdout pollution."""
import os
import sys

sys.path.insert(0, r"E:\work\code\agent-dev\desktop-agent")

# Capture stdout to ensure logging never writes there (would corrupt MCP protocol)
import io
old_stdout = sys.stdout
sys.stdout = io.StringIO()

from mio_cua import mcp_server

sys.stdout = old_stdout

log_file = mcp_server._LOG_FILE
print(f"Log file: {log_file}")
print(f"Exists: {os.path.exists(log_file)}")

# Emit test log lines from several layers
import logging
logging.getLogger("mio_cua.mcp").info("TEST-INFO from mcp")
logging.getLogger("mio_cua.perception").warning("TEST-WARNING from perception")
logging.getLogger("mio_cua.scene.omniparser").error("TEST-ERROR from omniparser")

print("\n=== Last 10 lines of log ===")
with open(log_file, "r", encoding="utf-8") as f:
    lines = f.readlines()
for line in lines[-10:]:
    print(line.rstrip())