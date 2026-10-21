"""Tests for workbook layout parsing."""

import datetime as dt
from pathlib import Path

import pandas as pd

from app.services.excel_importer import (
    E_RESTAURANT_ID,
    TIP_RESTAURANT_ID,
    ParsedMeal,
    parse_header_dates,
    parse_weekly_menus,
)
from app.services.excel_upload_service import build_upload_analysis


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


FIXTURES = Path(__file__).parent / "fixtures"


def _fixture_meals(name: str, today: dt.date) -> list[ParsedMeal]:
    """Parse a real uploaded workbook kept under tests/fixtures as-is."""
    df = pd.read_excel(FIXTURES / name, header=None)
    return parse_weekly_menus(df, today)


def test_september_workbook_parses_tip_breakfast() -> None:
    """'천원의 아침밥' 라벨과 분리된 시간 행도 TIP 조식으로 인식한다."""
    parsed = _fixture_meals("meal_2026_09.xlsx", dt.date(2026, 9, 14))

    breakfast = [m for m in parsed if m.meal_type == "breakfast"]
    assert {m.restaurant_id for m in breakfast} == {TIP_RESTAURANT_ID}
    assert [m.date for m in breakfast][:3] == [
        dt.date(2026, 9, 14),
        dt.date(2026, 9, 15),
        dt.date(2026, 9, 16),
    ]
    first = breakfast[0].menu
    assert first == ["①코너", "고추참치덮밥", "②코너", "주먹밥/치킨텐더샐러드"]
    for meal in breakfast:
        assert not any("아침밥" in item or "10:00" in item for item in meal.menu)

    lunch_menus = [m.menu for m in parsed if m.meal_type == "lunch"]
    assert all("②코너" not in menu for menu in lunch_menus)
    assert not any(
        m.meal_type == "breakfast" and m.restaurant_id == E_RESTAURANT_ID
        for m in parsed
    )
    assert not any("국내산" in item for m in parsed for item in m.menu)


def test_august_workbook_result_is_unchanged() -> None:
    """기존 '조식' 표기(8월 양식)는 조식·중식·석식이 그대로 파싱된다."""
    parsed = _fixture_meals("meal_2026_08.xlsx", dt.date(2026, 8, 5))

    kinds = {(m.restaurant_id, m.meal_type) for m in parsed}
    assert (TIP_RESTAURANT_ID, "breakfast") in kinds
    assert (TIP_RESTAURANT_ID, "lunch") in kinds
    assert (E_RESTAURANT_ID, "dinner") in kinds
    assert (E_RESTAURANT_ID, "breakfast") not in kinds


def test_upload_analysis_labels_breakfast() -> None:
    """업로드 분석 결과의 조식 항목 라벨은 '조식'이다."""
    parsed = _fixture_meals("meal_2026_09.xlsx", dt.date(2026, 9, 14))

    analysis = build_upload_analysis(parsed, {})

    labels = {
        item["meal_type_label"]
        for item in analysis["items"]
        if item["meal_type"] == "breakfast"
    }
    assert labels == {"조식"}


def test_typo_saturday_header_is_corrected() -> None:
    """원본의 TIP 토요일 오기 헤더는 정확한 날짜로 보정되어 받아들여진다."""
    sep = _fixture_meals("meal_2026_09.xlsx", dt.date(2026, 9, 14))
    aug = _fixture_meals("meal_2026_08.xlsx", dt.date(2026, 8, 5))

    def tip_dates(meals: list[ParsedMeal]) -> set[dt.date]:
        return {m.date for m in meals if m.restaurant_id == TIP_RESTAURANT_ID}

    assert dt.date(2026, 9, 19) in tip_dates(sep)
    assert dt.date(2026, 8, 10) in tip_dates(aug)
    assert sum(m.meal_type == "breakfast" for m in sep) == 6
    assert sum(m.meal_type == "breakfast" for m in aug) == 6


def test_header_rejected_without_majority() -> None:
    """과반이 같은 주와 일치하지 않으면 거부한다."""
    cells = ["8월", "5일", "9일", "3일", "20일"]
    assert parse_header_dates(cells, dt.date(2026, 8, 5)) == {}
