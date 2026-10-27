import logging

import pytest

from app.main import configure_app_logging


@pytest.fixture()
def app_logger():
    logger = logging.getLogger("app")
    saved = (logger.level, list(logger.handlers))
    logger.handlers.clear()
    yield logger
    logger.setLevel(saved[0])
    logger.handlers[:] = saved[1]


def test_app_info_logs_are_emitted(app_logger, capsys) -> None:
    configure_app_logging("INFO")

    logging.getLogger("app.ingest").info("notice labels attached: labeled=1")

    assert "app.ingest notice labels attached: labeled=1" in capsys.readouterr().err


def test_log_level_is_respected_and_handler_not_duplicated(app_logger) -> None:
    configure_app_logging("warning")
    configure_app_logging("warning")

    assert app_logger.level == logging.WARNING
    assert len(app_logger.handlers) == 1


def test_unknown_log_level_falls_back_to_info(app_logger) -> None:
    configure_app_logging("loud")

    assert app_logger.level == logging.INFO
