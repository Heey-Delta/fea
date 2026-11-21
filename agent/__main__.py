"""Agente da plataforma: python -m agent  (roda na VPS, ao lado do Docker)."""

import os
import signal
import threading
from pathlib import Path

from agent.agent import Agent
from core.config import get_settings
from core.db import get_sessionmaker
from core.logging import configure_logging


def main() -> int:
    settings = get_settings()
    configure_logging(settings.log_level)
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    agent = Agent(get_sessionmaker(), Path(os.environ.get("FEA_HOME", "/opt/fea")))
    agent.run_forever(float(os.environ.get("AGENT_INTERVAL", "15")), stop)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
