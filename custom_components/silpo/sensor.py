from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ACTIONABLE, DOMAIN
from .coordinator import SilpoCoordinator

PRODUCT_KEYS = ("lager_id", "name", "unit", "status", "model", "buys", "gap", "days_since", "due_in", "amount_per_buy", "base", "rate_per_week", "last", "last_price")


def _slim(p: dict) -> dict:
    return {k: p.get(k) for k in PRODUCT_KEYS}


def _by_status(d: dict, *statuses: str, limit: int = 60) -> list[dict]:
    return [_slim(p) for p in d["products"] if p["status"] in statuses][:limit]


@dataclass(frozen=True, kw_only=True)
class SilpoSensorDescription(SensorEntityDescription):
    value: Callable[[dict], Any]
    attrs: Callable[[dict], dict] = lambda d: {}


DESCRIPTIONS: tuple[SilpoSensorDescription, ...] = (
    SilpoSensorDescription(
        key="forecast", translation_key="forecast", icon="mdi:cart-arrow-down",
        value=lambda d: sum(d["status_counts"].get(s, 0) for s in ACTIONABLE),
        attrs=lambda d: {
            "asof": d["asof"], "counts": d["status_counts"],
            "overdue": _by_status(d, "overdue"), "due": _by_status(d, "due"), "soon": _by_status(d, "soon"),
            "stocked": _by_status(d, "stocked"), "lapsed": _by_status(d, "lapsed", limit=30),
            "shopping_list": [p["name"] for p in d["products"] if p["status"] in ACTIONABLE],
        }),
    SilpoSensorDescription(
        key="habits", translation_key="habits", icon="mdi:chart-timeline-variant",
        value=lambda d: d["habits"].get("trips_per_week"),
        attrs=lambda d: d["habits"] | {"sync": d.get("sync")}),
    SilpoSensorDescription(
        key="promo_matches", translation_key="promo_matches", icon="mdi:tag-heart",
        value=lambda d: len(d["promo"]["matches"]),
        attrs=lambda d: d["promo"]),
    SilpoSensorDescription(
        key="week_spend", translation_key="week_spend", native_unit_of_measurement="UAH", state_class=SensorStateClass.TOTAL,
        device_class=SensorDeviceClass.MONETARY, icon="mdi:cash",
        value=lambda d: d["habits"]["current_week"]["spend"]),
    SilpoSensorDescription(
        key="last_week_spend", translation_key="last_week_spend", native_unit_of_measurement="UAH", state_class=SensorStateClass.TOTAL,
        device_class=SensorDeviceClass.MONETARY, icon="mdi:cash-clock",
        value=lambda d: d["habits"]["last_week"]["spend"]),
    SilpoSensorDescription(
        key="week_trips", translation_key="week_trips", state_class=SensorStateClass.TOTAL, icon="mdi:store",
        value=lambda d: d["habits"]["current_week"]["trips"]),
    SilpoSensorDescription(
        key="avg_week_spend_4w", translation_key="avg_week_spend_4w", native_unit_of_measurement="UAH", state_class=SensorStateClass.MEASUREMENT, icon="mdi:chart-line",
        value=lambda d: d["habits"]["avg_week_spend_4w"], attrs=lambda d: {"prev_4w": d["habits"]["avg_week_spend_prev_4w"], "trend_pct": d["habits"]["trend_4w_pct"]}),
    SilpoSensorDescription(
        key="discount_pct", translation_key="discount_pct", native_unit_of_measurement="%", state_class=SensorStateClass.MEASUREMENT, icon="mdi:sale",
        value=lambda d: d["habits"]["discount_pct"]),
    SilpoSensorDescription(
        key="bonus_total", translation_key="bonus_total", state_class=SensorStateClass.TOTAL_INCREASING, icon="mdi:star-circle",
        value=lambda d: d["habits"]["bonus_total"]),
    SilpoSensorDescription(
        key="stored_receipts", translation_key="stored_receipts", state_class=SensorStateClass.TOTAL_INCREASING, icon="mdi:receipt-text",
        value=lambda d: d["sync"]["stored_receipts"], attrs=lambda d: d["sync"]),
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: SilpoCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(SilpoSensor(coordinator, entry, d) for d in DESCRIPTIONS)


class SilpoSensor(CoordinatorEntity[SilpoCoordinator], SensorEntity):
    _attr_has_entity_name = True
    entity_description: SilpoSensorDescription

    def __init__(self, coordinator: SilpoCoordinator, entry: ConfigEntry, description: SilpoSensorDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)}, name="Silpo", manufacturer="Сільпо", model="MCP", entry_type=None)

    @property
    def native_value(self) -> Any:
        try:
            return self.entity_description.value(self.coordinator.data)
        except (KeyError, TypeError):
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        try:
            return self.entity_description.attrs(self.coordinator.data)
        except (KeyError, TypeError):
            return {}
