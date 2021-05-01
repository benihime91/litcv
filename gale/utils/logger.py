# AUTOGENERATED! DO NOT EDIT! File to edit: nbs/00_utils.logger.ipynb (unless otherwise specified).

__all__ = ['setup_logger', 'log_main_process']

# Cell
# hide
"""
Modified from :
https://github.com/facebookresearch/detectron2/blob/9c7f8a142216ebc52d3617c11f8fafd75b74e637/detectron2/utils/logger.py#L119
"""

# Cell
import functools
import logging
import sys

from fastcore.all import ifnone
from pytorch_lightning.utilities import rank_zero_only
from termcolor import colored

# Cell
class _ColorfulFormatter(logging.Formatter):
    def __init__(self, *args, **kwargs):
        self._root_name = kwargs.pop("root_name") + "."
        self._abbrev_name = kwargs.pop("abbrev_name", "")
        if len(self._abbrev_name):
            self._abbrev_name = self._abbrev_name + "."
        super(_ColorfulFormatter, self).__init__(*args, **kwargs)

    def formatMessage(self, record):
        record.name = record.name.replace(self._root_name, self._abbrev_name)
        log = super(_ColorfulFormatter, self).formatMessage(record)
        if record.levelno == logging.WARNING:
            prefix = colored("WARNING", "red", attrs=["blink"])
        elif record.levelno == logging.ERROR or record.levelno == logging.CRITICAL:
            prefix = colored("ERROR", "red", attrs=["blink", "underline"])
        else:
            return log
        return prefix + " " + log

# Cell
@functools.lru_cache()  # so that calling setup_logger multiple times won't add many handlers
def setup_logger(distributed_rank=0, *, color=True, name="gale", level=logging.DEBUG):
    """
    Initialize the gale logger and set its verbosity level to `level`.
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False

    abbrev_name = name

    plain_formatter = logging.Formatter(
        "[%(asctime)s] %(name)s %(levelname)s: %(message)s", datefmt="%m/%d %H:%M:%S"
    )

    # stdout logging: master only
    if distributed_rank == 0:
        ch = logging.StreamHandler(stream=sys.stdout)
        ch.setLevel(logging.DEBUG)
        if color:
            formatter = _ColorfulFormatter(
                colored("[%(asctime)s %(name)s]: ", "green") + "%(message)s",
                datefmt="%m/%d %H:%M:%S",
                root_name=name,
                abbrev_name=str(abbrev_name),
            )
        else:
            formatter = plain_formatter
        ch.setFormatter(formatter)
        logger.addHandler(ch)
    return logger

# Cell
@rank_zero_only
def log_main_process(logger, lvl, msg):
    """
    Logs `msg` using `logger` only on the main process
    """
    logger.log(lvl, msg)