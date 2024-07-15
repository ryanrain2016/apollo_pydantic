import logging

debug_logger = logging.getLogger('apollo_pydantic.debug')
debug_logger.setLevel(logging.DEBUG)
logger = logging.getLogger('apollo_pydantic.general')

def enable_debug():
    logging.basicConfig(level=logging.DEBUG)