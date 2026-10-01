"""End-to-end smoke tests through the Streamlit UI (headless)."""

from streamlit.testing.v1 import AppTest


def app() -> AppTest:
    return AppTest.from_file("../app.py", default_timeout=30).run()


def test_example_data_renders_brief_figures():
    at = app()
    at.sidebar.button(key="load_example").click().run()
    assert not at.exception
    assert [m.value for m in at.metric] == ["8,410.00", "1,850.00", "10,260.00", "+133.33", "+126.67"]
    assert any("1 duplicates ignored" in s.value for s in at.success)


def test_messy_files_show_warnings_and_incomplete_valuation():
    at = app()
    at.sidebar.button(key="load_example").click().run()
    at.sidebar.selectbox(key="demo_file").select("messy_trades.csv").run()
    at.sidebar.button(key="demo_trades").click().run()
    assert not at.exception
    assert any("See the **Issues** tab" in w.value for w in at.warning)
    assert any("Valuation incomplete" in w.value for w in at.warning)  # NVDA has no price
    assert at.metric[2].value.endswith("*")


def test_wrong_file_type_is_reported():
    at = app()
    at.sidebar.button(key="load_example").click().run()
    at.sidebar.selectbox(key="demo_file").select("example_prices.csv").run()
    at.sidebar.button(key="demo_trades").click().run()
    assert any("whole file rejected" in e.value for e in at.error)
