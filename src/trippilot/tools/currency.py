"""Currency conversion: Frankfurter (ECB rates), with ExchangeRate-API's open endpoint for
currencies the ECB doesn't publish (PKR, AED, SAR, ...) or when Frankfurter is down."""

import logging

from trippilot.schemas import Money
from trippilot.tools._common import ExternalAPIError, ToolError, request_json, ttl_cache

log = logging.getLogger(__name__)

FRANKFURTER_URL = "https://api.frankfurter.dev/v1/latest"
OPEN_ER_URL = "https://open.er-api.com/v6/latest/{base}"

# Currencies published by the ECB (what Frankfurter supports).
ECB_CURRENCIES = {
    "AUD", "BGN", "BRL", "CAD", "CHF", "CNY", "CZK", "DKK", "EUR", "GBP", "HKD", "HUF",
    "IDR", "ILS", "INR", "ISK", "JPY", "KRW", "MXN", "MYR", "NOK", "NZD", "PHP", "PLN",
    "RON", "SEK", "SGD", "THB", "TRY", "USD", "ZAR",
}


def _frankfurter_rate(base: str, target: str) -> float:
    data = request_json("frankfurter", FRANKFURTER_URL, params={"base": base, "symbols": target})
    return float(data["rates"][target])


def _open_er_rate(base: str, target: str) -> float:
    data = request_json("open-er-api", OPEN_ER_URL.format(base=base))
    if data.get("result") != "success":
        raise ExternalAPIError("open-er-api", data.get("error-type", "unknown error"))
    try:
        return float(data["rates"][target])
    except KeyError as e:
        raise ToolError(f"Unsupported currency: {target}") from e


@ttl_cache(ttl=3600)
def get_rate(base: str, target: str) -> float:
    """Units of `target` per 1 unit of `base`."""
    base, target = base.upper(), target.upper()
    if base == target:
        return 1.0
    if base in ECB_CURRENCIES and target in ECB_CURRENCIES:
        try:
            return _frankfurter_rate(base, target)
        except (ExternalAPIError, KeyError) as e:
            log.warning("Frankfurter failed (%s); trying open.er-api.com", e)
    return _open_er_rate(base, target)


def convert(money: Money, to_currency: str) -> Money:
    """Convert a Money amount into another currency."""
    rate = get_rate(money.currency, to_currency)
    return Money(amount=round(money.amount * rate, 2), currency=to_currency.upper())
