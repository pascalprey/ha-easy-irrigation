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
    CONF_ENTRY_TYPE,
    CONF_ET0_SENSOR,
    CONF_FLOW,
    CONF_HUMIDITY_SENSOR,
    CONF_LEAD_TIME,
    CONF_MAX_BUCKET,
    CONF_MAX_DURATION,
    CONF_MODE,
    CONF_MULTIPLIER,
    CONF_NAME,
    CONF_RAIN_FORECAST_SENSOR,
    CONF_RAIN_SENSOR,
    CONF_RAIN_THRESHOLD,
    CONF_SOLAR_SENSOR,
    CONF_STAGE,
    CONF_SUNRISE_OFFSET,
    CONF_TEMP_MAX_SENSOR,
    CONF_TEMP_MIN_SENSOR,
    CONF_WIND_HEIGHT,
    CONF_WIND_SENSOR,
    CONF_WIND_UNIT,
    DEFAULTS,
    DOMAIN,
    ENTRY_TYPE_CONTROLLER,
    ENTRY_TYPE_ZONE,
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
        vol.Required(CONF_STAGE, default=d.get(CONF_STAGE, DEFAULTS[CONF_STAGE])): _num(
            "", minimum=1, maximum=20, step=1
        ),
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


def _controller_schema(d: dict[str, Any], *, include_name: bool) -> vol.Schema:
    fields: dict[Any, Any] = {}
    if include_name:
        fields[vol.Required(CONF_NAME, default=d.get(CONF_NAME, "Watering schedule"))] = (
            selector.TextSelector()
        )
    fields[
        vol.Required(
            CONF_SUNRISE_OFFSET, default=d.get(CONF_SUNRISE_OFFSET, DEFAULTS[CONF_SUNRISE_OFFSET])
        )
    ] = _num("min", minimum=0, maximum=240, step=1)
    fields[_opt(CONF_RAIN_FORECAST_SENSOR, d)] = _sensor()
    fields[
        vol.Required(
            CONF_RAIN_THRESHOLD, default=d.get(CONF_RAIN_THRESHOLD, DEFAULTS[CONF_RAIN_THRESHOLD])
        )
    ] = _num("mm", minimum=0, maximum=100, step=0.1)
    return vol.Schema(fields)


def _validate_calculated(user_input: dict[str, Any]) -> dict[str, str]:
    if not user_input.get(CONF_HUMIDITY_SENSOR) and not user_input.get(CONF_DEWPOINT_SENSOR):
        return {"base": "need_humidity_or_dewpoint"}
    return {}


class EasyIrrigationConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up a watering zone or a schedule controller."""

    VERSION = 1

    def __init__(self) -> None:
        self._base: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose what to add: a zone or a schedule controller."""
        return self.async_show_menu(
            step_id="user", menu_options=["zone", "controller"]
        )

    async def async_step_zone(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick the zone name and ET0 source mode."""
        if user_input is not None:
            self._base = {**user_input, CONF_ENTRY_TYPE: ENTRY_TYPE_ZONE}
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
        return self.async_show_form(step_id="zone", data_schema=schema)

    async def async_step_sensor(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                title=self._base[CONF_NAME], data={**self._base, **user_input}
            )
        return self.async_show_form(step_id="sensor", data_schema=_sensor_schema({}))

    async def async_step_calculated(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
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

    async def async_step_controller(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create a schedule controller that aggregates the zones."""
        if user_input is not None:
            return self.async_create_entry(
                title=user_input[CONF_NAME],
                data={**user_input, CONF_ENTRY_TYPE: ENTRY_TYPE_CONTROLLER},
            )
        return self.async_show_form(
            step_id="controller", data_schema=_controller_schema({}, include_name=True)
        )

    @staticmethod
    def async_get_options_flow(config_entry) -> OptionsFlow:
        return EasyIrrigationOptionsFlow()


class EasyIrrigationOptionsFlow(OptionsFlow):
    """Edit a zone or controller after setup (type is fixed at creation)."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        current = {**self.config_entry.data, **self.config_entry.options}
        if current.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_CONTROLLER:
            return await self.async_step_controller()
        if current.get(CONF_MODE) == MODE_CALCULATED:
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

    async def async_step_controller(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        current = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(
            step_id="controller",
            data_schema=_controller_schema(current, include_name=False),
        )
