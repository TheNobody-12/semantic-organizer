from src.semantic_organizer.cli import logger as cli_logger
from src.semantic_organizer.extraction.engine import logger as engine_logger

cli_logger.error("TEST_CLI_ERROR")
engine_logger.error("TEST_ENGINE_ERROR")
