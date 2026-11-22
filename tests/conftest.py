import os

# Do not pre-warm OmniParser in tests: it spawns a 10-20s model load on a
# background thread that would peg the CPU during the suite.
os.environ.setdefault("MIO_CUA_NO_PREWARM", "1")
