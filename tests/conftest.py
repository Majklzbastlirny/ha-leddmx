import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture(autouse=True)
def fake_bluetooth_loaded(hass):
    # Pretend the bluetooth stack is already set up so dependency setup is skipped.
    hass.config.components.update({"bluetooth", "bluetooth_adapters"})
    yield
