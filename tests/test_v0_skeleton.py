from decimal import Decimal

import pytest
from streamlit.testing.v1 import AppTest

from portfolio_monitor.application.service import PortfolioService
from portfolio_monitor.domain.value_objects import DomainError


def test_initialize_sets_cash_and_logs_command():
    svc = PortfolioService()
    svc.initialize("10000")
    assert svc.portfolio.cash == Decimal("10000")
    assert len(svc.log.entries) == 1


@pytest.mark.parametrize("raw", ["-1", "abc", "", "NaN"])
def test_initialize_rejects_invalid_cash(raw):
    with pytest.raises(DomainError):
        PortfolioService().initialize(raw)


def test_ui_creates_portfolio_and_shows_cash():
    at = AppTest.from_file("../app.py", default_timeout=30).run()
    assert not at.exception
    at.sidebar.button(key="init_button").click().run()
    assert not at.exception
    assert at.metric[0].value == "10,000.00"
