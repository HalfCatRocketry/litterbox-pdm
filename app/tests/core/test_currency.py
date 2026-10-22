"""Tests for the team's currency: the codes, writing amounts with the symbol, reading what was typed, the vault
setting, and the places costs are shown."""

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from litterbox.core import currency
from litterbox.core.part_number import PN
from litterbox.exporting import bom_csv
from litterbox.gui.logic import bom_text
from litterbox.gui.logic import purchasing_text
from litterbox.records import purchasing_info
from litterbox.references import bom
from litterbox.vault import config
from litterbox.vault import config_write


class Money(unittest.TestCase):
    def test_amounts_get_the_symbol_in_its_place(self):
        self.assertEqual(currency.money("12.5", "USD"), "$12.50")
        self.assertEqual(currency.money(Decimal("1234"), "SEK"), "1,234.00 kr")
        self.assertEqual(currency.money("0.1234", "GBP"), "£0.1234")              # never rounds a price away
        self.assertEqual(currency.money("3", None), "3.00")                       # no currency chosen
        self.assertEqual((currency.money("", "USD"), currency.money(None, "USD")), ("", ""))
        self.assertEqual(currency.money("n/a", "USD"), "n/a")

    def test_codes(self):
        self.assertEqual(currency.check(" usd "), "USD")
        self.assertIsNone(currency.check(""))
        with self.assertRaisesRegex(currency.CurrencyError, "isn't|not a currency"):
            currency.check("XYZ")
        self.assertEqual(currency.label("EUR"), "Euro (EUR, €)")
        self.assertEqual((currency.symbol("NOK"), currency.symbol_after("NOK"), currency.symbol(None)), ("kr", True, ""))

    def test_what_was_typed_loses_any_symbol(self):
        for typed, cost in (("$1,234.50", "1234.50"), ("12 kr", "12"), ("€3", "3"), ("USD 5", "5"), ("R$ 7.25", "7.25"),
                            ("0.10", "0.10")):
            self.assertEqual(purchasing_info.clean_cost(typed), cost, typed)


class Setting(unittest.TestCase):
    def test_kept_in_the_vault_settings_and_taken_off_again(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = Path(folder)
            config.config_path(repo).parent.mkdir(parents=True)
            config.config_path(repo).write_text("org: HCR\n", encoding="utf-8")
            self.assertIsNone(config.get_currency(repo))
            config_write.set_values(repo, currency="usd")
            self.assertEqual(config.get_currency(repo), "USD")
            config_write.set_values(repo, currency=None)
            self.assertNotIn("currency", config.load(repo))
            config.config_path(repo).write_text("org: HCR\ncurrency: nope\n", encoding="utf-8")
            with self.assertRaises(config.ConfigError):
                config.get_currency(repo)
            self.assertIsNone(config.currency_or_none(repo))                     # showing costs never fails


class Shown(unittest.TestCase):
    def test_details_bom_and_csv(self):
        self.assertIn(("Unit cost", "$0.42"), purchasing_text.details_rows({"unit_cost": "0.42"}, "USD"))
        self.assertIn(("Unit cost", ""), purchasing_text.details_rows({}, "USD"))
        line = bom.BomLine(1, PN("HCR", 4, 1), "A", "Bolt", quantity=3, total=6, purchasing={"unit_cost": "0.10"})
        row = dict(zip([c[0] for c in bom_text.COLUMNS], bom_text.table([line], bom.SINGLE, "EUR")[0][1]))
        self.assertEqual((row["cost"], row["ext"]), ("€0.10", "€0.60"))
        summary = bom.CostSummary(Decimal("22.00"), 2)
        self.assertEqual(bom_text.cost_text(summary, "USD"), "total cost $22.00")
        self.assertEqual(bom_csv.rows([line], summary, "USD")[0][13:15], ["Unit cost (USD)", "Total cost (USD)"])
        self.assertEqual(bom_csv.rows([line], summary, "USD")[1][13:15], ["0.10", "0.60"])       # numbers stay numbers


if __name__ == "__main__":
    unittest.main()
