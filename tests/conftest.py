import pytest

from sc2tray import i18n


@pytest.fixture(autouse=True)
def spanish():
    """Strings are checked in Spanish unless a test switches; the machine's language must not matter."""
    i18n.use("es")
    yield
    i18n.use("es")
