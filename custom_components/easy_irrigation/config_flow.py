"""Config and options flow for Easy Irrigation."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.helpers import selector

from .const import (
    CONF_AREA,
    CONF_DAYS_BETWEEN,
    CONF_DRAINAGE,
    CONF_ET0_SENSOR,
    CONF_FLOW,
    CONF_LEAD_TIME,
    CONF_MAX_BUCKET,
    CONF_MAX_DURATION,
    CONF_MULTIPLIER,
    CONF_NAME,
    DEFAULTS,
    DOMAIN,
)


def _number(unit: str, *, minimum: float, maximum: float, step: float) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=step,
            mode=selector.NumberSelectorMode.BOX,
            unit_of_measurement=unit,
        )
    )


def _schema(defaults: dict[str, Any], *, include_name: bool) -> vol.Schema:
    fields: dict[Any, Any] = {}
    if include_name:
        fields[vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, ""))] = (
            selector.TextSelector()
        )
    fields[vol.Required(CONF_ET0_SENSOR, default=defaults.get(CONF_ET0_SENSOR))] = (
        selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor"))
    )
    fields[vol.Required(CONF_AREA, default=defaults.get(CONF_AREA, DEFAULTS[CONF_AREA]))] = (
        _number("m²", minimum=0.1, maximum=100000, step=0.1)
    )
    fields[vol.Required(CONF_FLOW, default=defaults.get(CONF_FLOW, DEFAULTS[CONF_FLOW]))] = (
        _number("L/min", minimum=0.01, maximum=10000, step=0.1)
    )
    fields[vol.Required(CONF_MAX_BUCKET, default=defaults.get(CONF_MAX_BUCKET, DEFAULTS[CONF_MAX_BUCKET]))] = (
        _number("mm", minimum=0, maximum=1000, step=0.1)
    )
    fields[vol.Required(CONF_MULTIPLIER, default=defaults.get(CONF_MULTIPLIER, DEFAULTS[CONF_MULTIPLIER]))] = (
        _number("", minimum=0, maximum=10, step=0.05)
    )
    fields[vol.Required(CONF_LEAD_TIME, default=defaults.get(CONF_LEAD_TIME, DEFAULTS[CONF_LEAD_TIME]))] = (
        _number("s", minimum=0, maximum=3600, step=1)
    )
    fields[vol.Required(CONF_MAX_DURATION, default=defaults.get(CONF_MAX_DURATION, DEFAULTS[CONF_MAX_DURATION]))] = (
        _number("s", minimum=0, maximum=86400, step=1)
    )
    fields[vol.Required(CONF_DRAINAGE, default=defaults.get(CONF_DRAINAGE, DEFAULTS[CONF_DRAINAGE]))] = (
        _number("mm/h", minimum=0, maximum=100, step=0.01)
    )
    fields[vol.Required(CONF_DAYS_BETWEEN, default=defaults.get(CONF_DAYS_BETWEEN, DEFAULTS[CONF_DAYS_BETWEEN]))] = (
        _number("d", minimum=0, maximum=30, step=1)
    )
    return vol.Schema(fields)


class EasyIrrigationConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup: one zone per config entry."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect the parameters for a single irrigation zone."""
        if user_input is not None:
            return self.async_create_entry(
                title=user_input[CONF_NAME], data=user_input
            )
        return self.async_show_form(
            step_id="user", data_schema=_schema({}, include_name=True)
        )

    @staticmethod
    def async_get_options_flow(config_entry) -> OptionsFlow:
        """Return the options flow handler."""
        return EasyIrrigationOptionsFlow()


class EasyIrrigationOptionsFlow(OptionsFlow):
    """Allow editing the zone parameters after setup."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show and persist the editable zone parameters."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        current = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(
            step_id="init", data_schema=_schema(current, include_name=False)
        )
