import logging
# trunk-ignore(ruff/F401)
from colorama import Fore, Style
from config import testmode
from datetime import datetime


FORMAT = '%(levelname)s: %(asctime)s - %(message)s'
if testmode:
    logging.basicConfig(level=logging.DEBUG, format=FORMAT, datefmt='%H:%M:%S')
else:
    logging.basicConfig(level=logging.INFO, format=FORMAT, datefmt='%H:%M:%S')

def timenow():
    timestamp = datetime.now()
    timestamp = timestamp.replace(microsecond=(timestamp.microsecond // 10000) * 10000)
    return timestamp