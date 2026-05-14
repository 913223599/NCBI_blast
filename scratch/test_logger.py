import logging
import sys

class WebsocketsTransferFilter(logging.Filter):
    def filter(self, record):
        if record.exc_info:
            exc_type, exc_value, exc_tb = record.exc_info
            if isinstance(exc_value, OSError) and getattr(exc_value, 'winerror', None) == 121:
                return False
        return True

logger = logging.getLogger("websockets.server")
logger.setLevel(logging.DEBUG)
handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.DEBUG)
logger.addHandler(handler)
logger.addFilter(WebsocketsTransferFilter())

try:
    raise OSError(0, "test", None, 121)
except Exception as e:
    logger.error("data transfer failed", exc_info=True)

try:
    raise OSError(0, "other", None, 122)
except Exception as e:
    logger.error("other transfer failed", exc_info=True)
