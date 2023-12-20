import logging

from utils import init_app
import config

logging.basicConfig(format='%(asctime)s,%(msecs)03d %(levelname)-8s [%(filename)s:%(lineno)d] %(message)s',
    datefmt='%Y-%m-%d:%H:%M:%S',
    level=logging.DEBUG)\

def main():
    # TODO: change to use click instead
    init_app(config)


if __name__ == "__main__":
    main()
