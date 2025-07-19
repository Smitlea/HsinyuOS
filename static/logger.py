# -*- coding: utf8 -*-
import logging
from logging.handlers import TimedRotatingFileHandler
from colorama import init, Fore, Style
import os
import sys
import time


class ColoredFormatter(logging.Formatter):
    def format(self, record):
        if record.levelno == logging.INFO:
            record.msg = f"{Fore.GREEN}{record.msg}{Style.RESET_ALL}"
        elif record.levelno == logging.DEBUG:
            record.msg = f"{Fore.LIGHTWHITE_EX}{record.msg}{Style.RESET_ALL}"
        elif record.levelno == logging.WARNING:
            record.msg = f"{Fore.YELLOW}{record.msg}{Style.RESET_ALL}"
        elif record.levelno == logging.ERROR:
            record.msg = f"{Fore.LIGHTRED_EX}{record.msg}{Style.RESET_ALL}"
        return super().format(record)


def get_logger(name):
    module_name = os.path.splitext(os.path.basename(name))[0]
    log_path = f"{os.path.dirname(os.path.abspath(name))}/log/{module_name}"
    os.makedirs(log_path, exist_ok=True)

    formatter = ColoredFormatter(
        fmt="%(asctime)s [%(levelname)s] %(module)s:%(lineno)d %(funcName)s - %(message)s"
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.stream = open(sys.stdout.fileno(), mode='w', encoding='utf-8', closefd=False)
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(formatter)
    
    file_handler = TimedRotatingFileHandler(
        filename=f"{log_path}/{module_name}.log",
        when="midnight",
        backupCount=7
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    
    logging.basicConfig(level=logging.NOTSET, handlers= [file_handler, console_handler])

    return logging.getLogger(module_name)


if __name__ == "__main__":
    logger = get_logger(__file__)



    