import logging
from colorama import Fore, Style

FORMAT = '%(levelname)s: %(asctime)s - %(message)s'
logging.basicConfig(level=logging.DEBUG, format=FORMAT, datefmt='%H:%M:%S')
