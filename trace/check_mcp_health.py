"""Check MCP server processes and health."""
import psutil
import sys
import time
sys.stdout.reconfigure(encoding="utf-8")

print("=== Python / cua / mio processes ===")
for p in psutil.process_iter(["pid", "name", "cmdline", "memory_info", "create_time", "cpu_percent"]):
    try:
        name = p.info["name"] or ""
        cmdline = " ".join(p.info["cmdline"] or [])
        if any(k in name.lower() for k in ["cua", "mio"]) or "mcp_server" in cmdline or "mio_cua" in cmdline:
            mem = p.info["memory_info"].rss // 1024 // 1024
            age = time.time() - p.info["create_time"]
            hours = age / 3600
            print(f"  PID={p.info['pid']} name={name} mem={mem}MB age={hours:.1f}h")
            print(f"    cmd: {cmdline[:150]}")
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        continue
