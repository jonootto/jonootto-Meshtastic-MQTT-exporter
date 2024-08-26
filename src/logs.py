import logging
# trunk-ignore(ruff/F401)
from colorama import Fore, Style
from config import testmode


FORMAT = '%(levelname)s: %(asctime)s - %(message)s'
if testmode:
    logging.basicConfig(level=logging.DEBUG, format=FORMAT, datefmt='%H:%M:%S')
else:
    logging.basicConfig(level=logging.INFO, format=FORMAT, datefmt='%H:%M:%S')