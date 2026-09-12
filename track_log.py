from __future__ import annotations
try:
    from loguru import logger
except ImportError:
    import logging
    logging.basicConfig(level=logging.INFO, format='%(levelname)s [%(name)s] %(message)s')
    logger = logging.getLogger('tsn')
__all__ = ['logger']
