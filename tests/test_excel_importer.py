"""Tests for workbook layout parsing."""

import datetime as dt

import pandas as pd

from app.services.excel_importer import parse_weekly_menus


def workbook() -> pd.DataFrame:
    """Return a compact DataFrame matching the real workbook layout."""
    return pd.DataFrame(
        [
            ["◆TIP 학생식당 주간 식단표◆", "", "", "", "", "", ""],
            ["8월", "24일", "25일", "26일", "27일", "28일", "29일(토)"],
            ["조식", "미운영", "A", "B", "C", "D", "E"],
            ["9:00~10:00", "", "", "", "", "", ""],
            ["중식", "TIP 월", "TIP 화", "TIP 수", "TIP 목", "TIP 금", "TIP 토"],
            [
                "석식",
                "TIP 저",
                "TIP 화저",
                "TIP 수저",
                "TIP 목저",
                "TIP 금저",
                "TIP 토저",
            ],
            ["**상기 식단은", "", "", "", "", "", ""],
            ["◆E동 레스토랑 주간 식단표◆", "", "", "", "", "", ""],
            ["8월", "24일", "25일", "26일", "27일", "28일", "29일(토)"],
            ["중식", "E 월", "E 화", "E 수", "E 목", "E 금", "E 토"],
            ["석식", "E 저", "E 화저", "E 수저", "E 목저", "E 금저", "E 토저"],
        ]
    )


def test_parse_weekly_menus_includes_breakfast_and_first_label_row() -> None:
    """Meal labels themselves are the first menu row."""
    parsed = parse_weekly_menus(workbook(), dt.date(2026, 8, 24))

    breakfast = [meal for meal in parsed if meal.meal_type == "breakfast"]
    lunch = [meal for meal in parsed if meal.meal_type == "lunch"]
    dinner = [meal for meal in parsed if meal.meal_type == "dinner"]
    assert len(breakfast) == 6
    assert breakfast[0].menu == ["미운영"]
    assert lunch[0].menu == ["TIP 월"]
    assert dinner[-1].date == dt.date(2026, 8, 29)
    assert not any(
        meal.meal_type == "breakfast" and meal.restaurant_id == 2 for meal in parsed
    )


def test_parse_weekly_menus_rejects_one_partially_parsed_restaurant() -> None:
    """A date missing from only one required block rejects the whole workbook."""
    frame = workbook()
    frame.iloc[1, 2] = "99일"

    parsed = parse_weekly_menus(frame, dt.date(2026, 8, 24))

    assert parsed == []


def test_parse_weekly_menus_rejects_failed_required_restaurant_block() -> None:
    """A valid TIP block cannot hide a completely malformed E-dong block."""
    frame = workbook()
    frame.iloc[8, 0] = "잘못된 헤더"

    parsed = parse_weekly_menus(frame, dt.date(2026, 8, 24))

    assert parsed == []
