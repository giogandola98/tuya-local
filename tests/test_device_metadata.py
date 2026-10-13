"""Tests for optional device registry metadata."""

from types import SimpleNamespace

import pytest
from homeassistant.helpers import device_registry as dr

from custom_components.tuya_local.const import (
    CONF_DEVICE_ID,
    CONF_MAC_ADDRESS,
    CONF_VIA_DEVICE_ID,
)
from custom_components.tuya_local.device import TuyaLocalDevice
from custom_components.tuya_local.helpers.device_metadata import (
    update_metadata,
    validate_metadata,
)


@pytest.fixture
def registry(mocker):
    registry = mocker.MagicMock()
    registry.async_get_device.return_value = None
    mocker.patch(
        "custom_components.tuya_local.helpers.device_metadata.dr.async_get",
        return_value=registry,
    )
    return registry


@pytest.mark.parametrize(
    "raw", ["AA:BB:CC:DD:EE:FF", "aabbccddeeff", "aa-bb-cc-dd-ee-ff", "aabb.ccdd.eeff"]
)
def test_mac_normalization(registry, raw):
    data = {CONF_MAC_ADDRESS: raw}
    assert validate_metadata(None, {CONF_DEVICE_ID: "test"}, data) == {}
    assert data[CONF_MAC_ADDRESS] == "aa:bb:cc:dd:ee:ff"


def test_invalid_mac(registry):
    data = {CONF_MAC_ADDRESS: "not a mac"}
    assert validate_metadata(None, {CONF_DEVICE_ID: "test"}, data) == {
        CONF_MAC_ADDRESS: "invalid_mac"
    }


@pytest.mark.parametrize("selected", ["self", "child", "missing"])
def test_invalid_parent(registry, selected):
    devices = {
        "self": SimpleNamespace(id="self", via_device_id=None),
        "child": SimpleNamespace(id="child", via_device_id="self"),
    }
    registry.async_get_device.return_value = devices["self"]
    registry.async_get.side_effect = devices.get
    data = {CONF_VIA_DEVICE_ID: selected}
    assert validate_metadata(None, {CONF_DEVICE_ID: "test"}, data) == {
        CONF_VIA_DEVICE_ID: "invalid_via_device"
    }


def test_valid_parent(registry):
    registry.async_get.return_value = SimpleNamespace(id="router", via_device_id=None)
    data = {CONF_VIA_DEVICE_ID: "router"}
    assert validate_metadata(None, {CONF_DEVICE_ID: "test"}, data) == {}
    assert data[CONF_VIA_DEVICE_ID] == "router"


def test_clear_metadata_preserves_unrelated_connections(registry):
    old_mac = "aa:bb:cc:dd:ee:ff"
    registry.async_get_device.return_value = SimpleNamespace(
        id="self", connections={(dr.CONNECTION_NETWORK_MAC, old_mac), ("other", "keep")}
    )
    update_metadata(
        None,
        {CONF_DEVICE_ID: "test", CONF_MAC_ADDRESS: old_mac},
        {CONF_MAC_ADDRESS: "", CONF_VIA_DEVICE_ID: ""},
    )
    registry.async_update_device.assert_called_once_with(
        "self", new_connections={("other", "keep")}, via_device_id=None
    )


def test_metadata_in_device_info():
    device = TuyaLocalDevice.__new__(TuyaLocalDevice)
    device._name = "Test"
    device._manufacturer = None
    device._model = None
    device._mac_address = "aa:bb:cc:dd:ee:ff"
    device._via_device_id = "router"
    device.dev_cid = None
    device._api = SimpleNamespace(id="test", cid=None)
    assert device.device_info["connections"] == {
        (dr.CONNECTION_NETWORK_MAC, device._mac_address)
    }
    assert device.device_info["via_device_id"] == "router"


@pytest.mark.asyncio
async def test_details_flow_stores_metadata(registry, mocker):
    from custom_components.tuya_local.config_flow import ConfigFlowHandler

    flow = ConfigFlowHandler()
    flow.hass = mocker.MagicMock()
    flow.hass.async_add_executor_job = mocker.AsyncMock()
    flow.data = {CONF_DEVICE_ID: "test", "type": "smartplugv1"}
    registry.async_get.return_value = SimpleNamespace(id="router", via_device_id=None)
    create_entry = mocker.patch.object(flow, "async_create_entry")
    await flow.async_step_choose_entities(
        {"name": "Test", CONF_MAC_ADDRESS: "AABBCCDDEEFF", CONF_VIA_DEVICE_ID: "router"}
    )
    saved = create_entry.call_args.kwargs["data"]
    assert saved[CONF_MAC_ADDRESS] == "aa:bb:cc:dd:ee:ff"
    assert saved[CONF_VIA_DEVICE_ID] == "router"


@pytest.mark.asyncio
async def test_details_flow_rejects_invalid_metadata(registry, mocker):
    from custom_components.tuya_local.config_flow import ConfigFlowHandler

    flow = ConfigFlowHandler()
    flow.hass = mocker.MagicMock()
    flow.hass.async_add_executor_job = mocker.AsyncMock(
        return_value=SimpleNamespace(name="Test")
    )
    flow.data = {CONF_DEVICE_ID: "test", "type": "smartplugv1"}
    show_form = mocker.patch.object(flow, "async_show_form")
    create_entry = mocker.patch.object(flow, "async_create_entry")
    await flow.async_step_choose_entities({"name": "Test", CONF_MAC_ADDRESS: "bad"})
    assert show_form.call_args.kwargs["errors"] == {CONF_MAC_ADDRESS: "invalid_mac"}
    create_entry.assert_not_called()


@pytest.mark.asyncio
async def test_options_flow_updates_metadata(registry, mocker):
    from custom_components.tuya_local.config_flow import OptionsFlowHandler

    flow = OptionsFlowHandler()
    flow.hass = mocker.MagicMock()
    entry = SimpleNamespace(
        data={CONF_DEVICE_ID: "test", "type": "smartplugv1"}, options={}
    )
    mocker.patch.object(
        OptionsFlowHandler,
        "config_entry",
        new_callable=mocker.PropertyMock,
        return_value=entry,
    )
    registry.async_get_device.return_value = SimpleNamespace(
        id="self", connections=set(), via_device_id=None
    )
    registry.async_get.return_value = SimpleNamespace(id="router", via_device_id=None)
    mocker.patch(
        "custom_components.tuya_local.config_flow.async_test_connection",
        new=mocker.AsyncMock(return_value=True),
    )
    create_entry = mocker.patch.object(flow, "async_create_entry")
    await flow.async_step_user(
        {
            "protocol_version": "auto",
            CONF_MAC_ADDRESS: "AABBCCDDEEFF",
            CONF_VIA_DEVICE_ID: "router",
        }
    )
    registry.async_update_device.assert_called_once_with(
        "self",
        new_connections={(dr.CONNECTION_NETWORK_MAC, "aa:bb:cc:dd:ee:ff")},
        via_device_id="router",
    )
    assert (
        create_entry.call_args.kwargs["data"][CONF_MAC_ADDRESS] == "aa:bb:cc:dd:ee:ff"
    )
