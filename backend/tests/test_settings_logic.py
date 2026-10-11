"""Settings validation and merging (no database)."""

from decimal import Decimal

import pytest

from app.services.app_settings import SPECS, SettingError, merged, server_defaults, to_effective, validate


def test_whole_numbers_are_checked_against_their_range():
    assert validate("billing.lead_days", 5) == 5
    assert validate("billing.lead_days", " 7 ") == 7
    assert validate("billing.lead_days", "0") == 0
    assert validate("late_fee.grace_days", 90) == 90
    for bad in (-1, 61, "abc", "5.5", "", None, True, 1.5, "1e3"):
        with pytest.raises(SettingError):
            validate("billing.lead_days", bad)
    with pytest.raises(SettingError, match="0 to 90"):
        validate("late_fee.grace_days", 91)


def test_urdu_digits_typed_by_staff_are_understood_and_stored_as_normal_numbers():
    assert validate("billing.lead_days", "۵") == 5
    assert validate("late_fee.amount", "۱۰۰") == "100.00"


def test_money_is_exact_and_never_a_float():
    assert validate("late_fee.amount", "100") == "100.00"
    assert validate("late_fee.amount", "100.5") == "100.50"
    assert validate("late_fee.amount", 250) == "250.00"
    assert validate("late_fee.amount", "0") == "0.00"
    for bad in ("-5", "1,000", "10.555", "abc", "", 1.5, True, None, "1000000000", "Rs 5"):
        with pytest.raises(SettingError):
            validate("late_fee.amount", bad)


def test_choices_text_and_unknown_keys():
    assert validate("import.recharge_date_means", "LAST_RECHARGE") == "LAST_RECHARGE"
    with pytest.raises(SettingError, match="NEXT_DUE"):
        validate("import.recharge_date_means", "SOMETIMES")
    assert validate("company.name", "  My   ISP  ") == "My ISP"
    assert validate("company.phone", "") == ""
    with pytest.raises(SettingError, match="at most 120"):
        validate("company.name", "x" * 121)
    with pytest.raises(SettingError, match="enter text"):
        validate("company.name", 5)
    with pytest.raises(SettingError, match="Unknown setting"):
        validate("billing.something_else", 1)


def test_every_setting_has_a_default_that_is_itself_valid():
    defaults = server_defaults()
    assert set(defaults) == set(SPECS)
    for key, value in defaults.items():
        assert validate(key, value) == value or str(validate(key, value)) == str(value), key


def test_saved_values_override_the_defaults_and_bad_ones_are_ignored():
    base = server_defaults()
    out = merged({"billing.lead_days": 9, "late_fee.amount": "75", "company.name": "Fast Net"})
    assert out["billing.lead_days"] == 9 and out["late_fee.amount"] == "75.00" and out["company.name"] == "Fast Net"
    assert out["late_fee.grace_days"] == base["late_fee.grace_days"]          # untouched
    # a stored value that has become invalid must not break billing: the default is used
    broken = merged({"billing.lead_days": 9999, "late_fee.amount": "abc", "nonsense": 1})
    assert broken["billing.lead_days"] == base["billing.lead_days"]
    assert broken["late_fee.amount"] == base["late_fee.amount"]
    assert "nonsense" not in broken


def test_effective_has_the_right_types():
    e = to_effective(merged({"late_fee.amount": "50", "billing.lead_days": 3}))
    assert e.late_fee_amount == Decimal("50.00") and isinstance(e.late_fee_amount, Decimal)
    assert e.billing_lead_days == 3 and isinstance(e.billing_lead_days, int)
    assert e.recharge_date_means in ("NEXT_DUE", "LAST_RECHARGE")
