"""Config and options flow for Easy Irrigation."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.helpers import selector

from .const import (
    CONF_AREA,
    CONF_DAYS_BETWEEN,
    CONF_DEWPOINT_SENSOR,
    CONF_DRAINAGE,
    CONF_ET0_SENSOR,
    CONF_FLOW,
    CONF_HUMIDITY_SENSOR,
    CONF_LEAD_TIME,
    CONF_MAX_BUCKET,
    CONF_MAX_DURATION,
    CONF_MODE,
    CONF_MULTIPLIER,
    CONF_NAME,
    CONF_RAIN_SENSOR,
    CONF_SOLAR_SENSOR,
    CONF_TEMP_MAX_SENSOR,
    CONF_TEMP_MIN_SENSOR,
    CONF_WIND_HEIGHT,
    CONF_WIND_SENSOR,
    CONF_WIND_UNIT,
    DEFAULTS,
    DOMAIN,
    MODE_CALCULATED,
    MODE_SENSOR,
    WIND_UNIT_KMH,
    WIND_UNIT_MS,
)


def _num(unit: str, *, minimum: float, maximum: float, step: float) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=step,
            mode=selector.NumberSelectorMode.BOX,
            unit_of_measurement=unit,
        )
    )


def _sensor() -> selector.EntitySelector:
    return selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor"))


def _req(key: str, defaults: dict[str, Any]) -> vol.Required:
    value = defaults.get(key)
    return vol.Required(key, default=value) if value is not None else vol.Required(key)


def _opt(key: str, defaults: dict[str, Any]) -> vol.Optional:
    return vol.Optional(key, description={"suggested_value": defaults.get(key)})


def _zone_fields(d: dict[str, Any]) -> dict[Any, Any]:
    return {
        vol.Required(CONF_AREA, default=d.get(CONF_AREA, DEFAULTS[CONF_AREA])): _num(
            "m²", minimum=0.1, maximum=100000, step=0.1
        ),
        vol.Required(CONF_FLOW, default=d.get(CONF_FLOW, DEFAULTS[CONF_FLOW])): _num(
            "L/min", minimum=0.01, maximum=10000, step=0.1
        ),
        vol.Required(
            CONF_MAX_BUCKET, default=d.get(CONF_MAX_BUCKET, DEFAULTS[CONF_MAX_BUCKET])
        ): _num("mm", minimum=0, maximum=1000, step=0.1),
        vol.Required(
            CONF_MULTIPLIER, default=d.get(CONF_MULTIPLIER, DEFAULTS[CONF_MULTIPLIER])
        ): _num("", minimum=0, maximum=10, step=0.05),
        vol.Required(
            CONF_LEAD_TIME, default=d.get(CONF_LEAD_TIME, DEFAULTS[CONF_LEAD_TIME])
        ): _num("s", minimum=0, maximum=3600, step=1),
        vol.Required(
            CONF_MAX_DURATION, default=d.get(CONF_MAX_DURATION, DEFAULTS[CONF_MAX_DURATION])
        ): _num("s", minimum=0, maximum=86400, step=1),
        vol.Required(
            CONF_DRAINAGE, default=d.get(CONF_DRAINAGE, DEFAULTS[CONF_DRAINAGE])
        ): _num("mm/h", minimum=0, maximum=100, step=0.01),
        vol.Required(
            CONF_DAYS_BETWEEN, default=d.get(CONF_DAYS_BETWEEN, DEFAULTS[CONF_DAYS_BETWEEN])
        ): _num("d", minimum=0, maximum=30, step=1),
    }


def _sensor_schema(d: dict[str, Any]) -> vol.Schema:
    return vol.Schema({_req(CONF_ET0_SENSOR, d): _sensor(), **_zone_fields(d)})


def _calculated_schema(d: dict[str, Any]) -> vol.Schema:
    fields: dict[Any, Any] = {
        _req(CONF_TEMP_MIN_SENSOR, d): _sensor(),
        _req(CONF_TEMP_MAX_SENSOR, d): _sensor(),
        _opt(CONF_HUMIDITY_SENSOR, d): _sensor(),
        _opt(CONF_DEWPOINT_SENSOR, d): _sensor(),
        _req(CONF_WIND_SENSOR, d): _sensor(),
        vol.Required(CONF_WIND_UNIT, default=d.get(CONF_WIND_UNIT, WIND_UNIT_MS)): (
            selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[WIND_UNIT_MS, WIND_UNIT_KMH],
                    translation_key="wind_unit",
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )
        ),
        vol.Required(
            CONF_WIND_HEIGHT, default=d.get(CONF_WIND_HEIGHT, DEFAULTS[CONF_WIND_HEIGHT])
        ): _num("m", minimum=0.5, maximum=50, step=0.5),
        _opt(CONF_SOLAR_SENSOR, d): _sensor(),
        _opt(CONF_RAIN_SENSOR, d): _sensor(),
    }
    fields.update(_zone_fields(d))
    return vol.Schema(fields)


def _validate_calculated(user_input: dict[str, Any]) -> dict[str, str]:
    if not user_input.get(CONF_HUMIDITY_SENSOR) and not user_input.get(CONF_DEWPOINT_SENSOR):
        return {"base": "need_humidity_or_dewpoint"}
    return {}


class EasyIrrigationConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up one irrigation zone per config entry."""

    VERSION = 1

    def __init__(self) -> None:
        self._base: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick the zone name and the ET0 source mode."""
        if user_input is not None:
            self._base = user_input
            if user_input[CONF_MODE] == MODE_SENSOR:
                return await self.async_step_sensor()
            return await self.async_step_calculated()

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME): selector.TextSelector(),
                vol.Required(CONF_MODE, default=MODE_SENSOR): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[MODE_SENSOR, MODE_CALCULATED],
                        translation_key="et0_mode",
                        mode=selector.SelectSelectorMode.LIST,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_sensor(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Mode 'sensor': an ET0 sensor plus the zone parameters."""
        if user_input is not None:
            return self.async_create_entry(
                title=self._base[CONF_NAME], data={**self._base, **user_input}
            )
        return self.async_show_form(step_id="sensor", data_schema=_sensor_schema({}))

    async def async_step_calculated(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Mode 'calculated': weather sensors plus the zone parameters."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate_calculated(user_input)
            if not errors:
                return self.async_create_entry(
                    title=self._base[CONF_NAME], data={**self._base, **user_input}
                )
        return self.async_show_form(
            step_id="calculated",
            data_schema=_calculated_schema(user_input or {}),
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(config_entry) -> OptionsFlow:
        """Return the options flow handler."""
        return EasyIrrigationOptionsFlow()


class EasyIrrigationOptionsFlow(OptionsFlow):
    """Edit the zone parameters after setup (mode is fixed at creation)."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Route to the editor matching the entry's ET0 mode."""
        current = {**self.config_entry.data, **self.config_entry.options}
        if current.get(CONF_MODE, MODE_SENSOR) == MODE_CALCULATED:
            return await self.async_step_calculated()
        return await self.async_step_sensor()

    async def async_step_sensor(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        current = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(step_id="sensor", data_schema=_sensor_schema(current))

    async def async_step_calculated(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate_calculated(user_input)
            if not errors:
                return self.async_create_entry(title="", data=user_input)
            current = user_input
        else:
            current = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(
            step_id="calculated", data_schema=_calculated_schema(current), errors=errors
        )
