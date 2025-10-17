from sys import version_info

assert version_info >= (3, 7), "pollevbot requires python 3.7 or later"

from .pollbot import PollBot
import logging
import os

# Log all messages as white text
WHITE = "\033[1m"
_log_level_name = os.getenv("LOGLEVEL", "INFO").upper()
_log_level = getattr(logging, _log_level_name, logging.INFO)
if _log_level_name not in logging._nameToLevel:
    logging.warning("Unknown LOGLEVEL '%s'; defaulting to INFO", _log_level_name)
    _log_level = logging.INFO
logging.basicConfig(level=_log_level,
                    format=WHITE + "%(asctime)s.%(msecs)03d [%(name)s] "
                                   "%(levelname)s: %(message)s",
                    datefmt='%Y-%m-%d %H:%M:%S')
