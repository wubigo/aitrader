import logging
import sys

def setup_logging():
    """Configures logging for the entire project."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        stream=sys.stdout # Ensure logs are directed to stdout
    )
    # Get the root logger to ensure basicConfig is applied
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Ensure the root logger has at least one handler to stream to stdout
    if not root_logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)

    # Iterate through all existing loggers and set their level, especially for tqsdk
    for name in logging.Logger.manager.loggerDict:
        if name.startswith('tqsdk'):
            logger = logging.getLogger(name)
            logger.setLevel(logging.INFO)
            # If tqsdk's logger has its own handlers, ensure their levels are also INFO
            for handler in logger.handlers:
                if handler.level < logging.INFO:
                    handler.setLevel(logging.INFO)

if __name__ == "__main__":
    setup_logging()
    # Example usage
    logger = logging.getLogger(__name__)
    logger.info("Logging configured and working from utils/logging_config.py example.")
    logger.warning("This is a warning.")
