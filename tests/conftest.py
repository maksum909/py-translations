import pytest
from django.utils import translation


@pytest.fixture(autouse=True)
def _active_english():
    translation.activate("en")
    yield
    translation.deactivate_all()
