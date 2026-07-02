import logging
import sys


def setup_logging(level: str = "INFO") -> None:
    root = logging.getLogger("agent_atlas")
    if root.handlers:
        return  # already configured -- avoid duplicate handlers on reload
    root.setLevel(level)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    ))
    root.addHandler(handler)
