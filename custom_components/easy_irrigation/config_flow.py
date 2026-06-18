"""Config and options flow for Easy Irrigation."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.helpers import selector

from .const import (
    CONF_ADD_ANOTHER,
    CONF_AREA,
    CONF_CALC_TIME,
    CONF_DEWPOINT_SENSOR,
    CONF_DRAINAGE,
    CONF_ENTRY_TYPE,
    CONF_ET0_SENSOR,
    CONF_FLOW,
    CONF_HUMIDITY_SENSOR,
    CONF_LEAD_TIME,
    CONF_MAX_BUCKET,
    CONF_MAX_DURATION,
    CONF_MIN_DAYS_BETWEEN,
    CONF_MODE,
    CONF_MULTIPLIER,
    CONF_NAME,
    CONF_PHASE_ZONES,
    CONF_PHASES,
    CONF_RAIN_SENSOR,
    CONF_RAIN_THRESHOLD,
    CONF_RUN_VALVES,
    CONF_SOLAR_SENSOR,
    CONF_SUNRISE_OFFSET,
    CONF_TEMP_MAX_SENSOR,
    CONF_TEMP_MIN_SENSOR,
    CONF_VALVE_ENTITY,
    CONF_WEATHER_ENTITY,
    CONF_WIND_HEIGHT,
    CONF_WIND_SENSOR,
    CONF_WIND_UNIT,
    DEFAULT_CALC_TIME,
    DEFAULT_RUN_VALVES,
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


def _valve() -> selector.EntitySelector:
    return selector.EntitySelector(
        selector.EntitySelectorConfig(domain=["switch", "valve"])
    )


def _req(key: str, defaults: dict[str, Any]) -> vol.Required:
    value = defaults.get(key)
    return vol.Required(key, default=value) if value is not None else vol.Required(key)


def _opt(key: str, defaults: dict[str, Any]) -> vol.Optional:
    return vol.Optional(key, description={"suggested_value": defaults.get(key)})


def _zone_fields(d: dict[str, Any]) -> dict[Any, Any]:
    return {
        _opt(CONF_VALVE_ENTITY, d): _valve(),
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
            CONF_MIN_DAYS_BETWEEN,
            default=d.get(CONF_MIN_DAYS_BETWEEN, DEFAULTS[CONF_MIN_DAYS_BETWEEN]),
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
    fields[
        vol.Required(CONF_CALC_TIME, default=d.get(CONF_CALC_TIME, DEFAULT_CALC_TIME))
    ] = selector.TimeSelector()
    fields[
        vol.Required(CONF_RUN_VALVES, default=d.get(CONF_RUN_VALVES, DEFAULT_RUN_VALVES))
    ] = selector.BooleanSelector()
    fields[_opt(CONF_WEATHER_ENTITY, d)] = selector.EntitySelector(
        selector.EntitySelectorConfig(domain="weather")
    )
    fields[
        vol.Required(
            CONF_RAIN_THRESHOLD, default=d.get(CONF_RAIN_THRESHOLD, DEFAULTS[CONF_RAIN_THRESHOLD])
        )
    ] = _num("mm", minimum=0, maximum=100, step=0.1)
    return vol.Schema(fields)


def _phase_schema(
    exclude: list[str], default_zones: list[str], add_default: bool
) -> vol.Schema:
    return vol.Schema(
        {
            vol.Optional(CONF_PHASE_ZONES, default=default_zones): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="sensor",
                    integration=DOMAIN,
                    device_class="duration",
                    multiple=True,
                    exclude_entities=exclude,
                )
            ),
            vol.Required(CONF_ADD_ANOTHER, default=add_default): selector.BooleanSelector(),
        }
    )


def _validate_calculated(user_input: dict[str, Any]) -> dict[str, str]:
    if not user_input.get(CONF_HUMIDITY_SENSOR) and not user_input.get(CONF_DEWPOINT_SENSOR):
        return {"base": "need_humidity_or_dewpoint"}
    return {}


def _phase_step(flow: Any, user_input: dict[str, Any] | None, *, create_title: str | None):
    """Shared phase-loop body for the config and options flows."""
    if user_input is not None:
        zones = user_input.get(CONF_PHASE_ZONES) or []
        if zones:
            flow._phases.append(zones)
        if user_input.get(CONF_ADD_ANOTHER):
            flow._phase_idx += 1
            return None  # caller re-enters async_step_phase
        data = {**flow._ctrl, CONF_PHASES: flow._phases}
        title = create_title if create_title is not None else ""
        return flow.async_create_entry(title=title, data=data)

    used = [s for phase in flow._phases for s in phase]
    default_zones = (
        flow._existing_phases[flow._phase_idx]
        if flow._phase_idx < len(flow._existing_phases)
        else []
    )
    add_default = (flow._phase_idx + 1) < len(flow._existing_phases)
    return flow.async_show_form(
        step_id="phase",
        data_schema=_phase_schema(used, default_zones, add_default),
        description_placeholders={"n": str(len(flow._phases) + 1)},
    )


class EasyIrrigationConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up a watering zone or a schedule controller."""

    VERSION = 1

    def __init__(self) -> None:
        self._base: dict[str, Any] = {}
        self._ctrl: dict[str, Any] = {}
        self._phases: list[list[str]] = []
        self._existing_phases: list[list[str]] = []
        self._phase_idx: int = 0

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_show_menu(step_id="user", menu_options=["zone", "controller"])

    async def async_step_zone(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
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
        if user_input is not None:
            self._ctrl = {**user_input, CONF_ENTRY_TYPE: ENTRY_TYPE_CONTROLLER}
            self._phases = []
            self._existing_phases = []
            self._phase_idx = 0
            return await self.async_step_phase()
        return self.async_show_form(
            step_id="controller", data_schema=_controller_schema({}, include_name=True)
        )

    async def async_step_phase(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        result = _phase_step(self, user_input, create_title=self._ctrl.get(CONF_NAME))
        if result is None:
            return await self.async_step_phase()
        return result

    @staticmethod
    def async_get_options_flow(config_entry) -> OptionsFlow:
        return EasyIrrigationOptionsFlow()


class EasyIrrigationOptionsFlow(OptionsFlow):
    """Edit a zone or controller after setup (type is fixed at creation).

    The phase-loop attributes (``_ctrl``, ``_phases``, ``_existing_phases``,
    ``_phase_idx``) are initialised in :meth:`async_step_controller` before the
    loop is entered, so no custom ``__init__`` (which could interfere with the
    framework-managed ``config_entry``) is needed.
    """

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
            self._ctrl = user_input
            self._phases = []
            current = {**self.config_entry.data, **self.config_entry.options}
            self._existing_phases = current.get(CONF_PHASES) or []
            self._phase_idx = 0
            return await self.async_step_phase()
        current = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(
            step_id="controller",
            data_schema=_controller_schema(current, include_name=False),
        )

    async def async_step_phase(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        result = _phase_step(self, user_input, create_title=None)
        if result is None:
            return await self.async_step_phase()
        return result
