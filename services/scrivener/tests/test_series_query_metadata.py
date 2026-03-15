from src.query.series import _infer_units


def test_infer_units_for_bls_hourly_earnings() -> None:
    assert _infer_units(
        external_id="CES0500000003",
        name="Average Hourly Earnings, Private",
        units=None,
        source="BLS",
    ) == "Dollars per hour"


def test_infer_units_for_bls_weekly_earnings() -> None:
    assert _infer_units(
        external_id="CES0500000011",
        name="Average Weekly Earnings, Private",
        units=None,
        source="BLS",
    ) == "Dollars per week"


def test_infer_units_for_jolts_levels() -> None:
    assert _infer_units(
        external_id="JTS000000000000000JOL",
        name="Job Openings Level",
        units=None,
        source="BLS",
    ) == "Thousands of jobs"


def test_infer_units_for_bls_rates() -> None:
    assert _infer_units(
        external_id="LNS14000000",
        name="Unemployment Rate",
        units=None,
        source="BLS",
    ) == "Percent"
