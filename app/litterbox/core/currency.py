"""
currency.py - the team's currency (a vault setting, `currency` in .litterbox/config.yaml): the currencies an Admin can
pick, and writing an amount with its symbol ($12.50, 12,50 kr). Unit costs are stored as plain numbers in the
team's currency (records/purchasing_info.py); only what people read carries the symbol.

    money("12.5", "USD") -> "$12.50"         money(Decimal("1234"), "SEK") -> "1,234.00 kr"
    money("12.5", None) -> "12.50"            no currency chosen: the number alone, as before 0.5.3
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


@dataclass(frozen=True)
class Currency:
    code: str           # ISO 4217, the value kept in the settings file
    name: str
    symbol: str
    after: bool = False  # the symbol goes after the amount (12.50 kr)


CURRENCIES = (
    Currency("USD", "US Dollar", "$"), Currency("CAD", "Canadian Dollar", "CA$"),
    Currency("AUD", "Australian Dollar", "A$"), Currency("NZD", "New Zealand Dollar", "NZ$"),
    Currency("EUR", "Euro", "€"), Currency("GBP", "Pound Sterling", "£"), Currency("CHF", "Swiss Franc", "CHF "),
    Currency("JPY", "Japanese Yen", "¥"), Currency("CNY", "Chinese Yuan", "CN¥"), Currency("INR", "Indian Rupee", "₹"),
    Currency("KRW", "South Korean Won", "₩"), Currency("SGD", "Singapore Dollar", "S$"),
    Currency("HKD", "Hong Kong Dollar", "HK$"), Currency("MXN", "Mexican Peso", "MX$"),
    Currency("BRL", "Brazilian Real", "R$"), Currency("ZAR", "South African Rand", "R "),
    Currency("SEK", "Swedish Krona", " kr", after=True), Currency("NOK", "Norwegian Krone", " kr", after=True),
    Currency("DKK", "Danish Krone", " kr", after=True), Currency("PLN", "Polish Zloty", " zł", after=True),
    Currency("CZK", "Czech Koruna", " Kč", after=True), Currency("ILS", "Israeli New Shekel", "₪"),
    Currency("AED", "UAE Dirham", "AED "), Currency("TWD", "New Taiwan Dollar", "NT$"),
)
BY_CODE = {currency.code: currency for currency in CURRENCIES}


class CurrencyError(ValueError):
    """Not a currency Litterbox knows. The message is safe to show."""


def check(code):
    """A currency code as kept in the settings ('usd' -> 'USD'), or None for none. Raises CurrencyError."""
    if code in (None, ""):
        return None
    text = str(code).strip().upper()
    if text not in BY_CODE:
        raise CurrencyError(f"'{code}' is not a currency Litterbox knows (use a code like USD or EUR).")
    return text


def label(code):
    """'US Dollar (USD, $)' for the Vault Settings list."""
    currency = BY_CODE[code]
    return f"{currency.name} ({currency.code}, {currency.symbol.strip()})"


def symbol(code):
    """'$', 'kr' or '' when no currency is chosen (or it isn't known)."""
    currency = BY_CODE.get(code or "")
    return currency.symbol.strip() if currency else ""


def symbol_after(code):
    """True when the symbol is written after the amount (12.50 kr)."""
    currency = BY_CODE.get(code or "")
    return bool(currency and currency.after)


def money(amount, code=None, places=2):
    """An amount (a Decimal, a number or the text a record keeps) with the currency's symbol, at least `places`
    decimals and thousands commas. '' for '' or None; text that isn't a number is returned as it is."""
    if amount in (None, ""):
        return ""
    try:
        value = Decimal(str(amount))
    except InvalidOperation:
        return str(amount)
    decimals = max(places, -value.as_tuple().exponent if value.as_tuple().exponent < 0 else 0)
    text = f"{value:,.{decimals}f}"
    currency = BY_CODE.get(code or "")
    if currency is None:
        return text
    return text + currency.symbol if currency.after else currency.symbol + text


def strip_symbols(text):
    """What was typed for a cost, without any currency symbol or code Litterbox knows ('$1,234.50' -> '1,234.50',
    '12 kr' -> '12')."""
    text = str(text if text is not None else "").strip()
    marks = sorted({c.symbol.strip() for c in CURRENCIES} | set(BY_CODE) | {"$", "€", "£", "¥"}, key=len, reverse=True)
    while True:
        cut = next((text[len(mark):] if text.startswith(mark) else text[:-len(mark)]
                    for mark in marks if text.startswith(mark) or text.endswith(mark)), None)
        if cut is None:
            return text
        text = cut.strip()                  # shorter each time round, so this ends
