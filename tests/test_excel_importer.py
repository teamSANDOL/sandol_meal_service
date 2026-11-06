"""Tests for workbook layout parsing."""

import datetime as dt
from pathlib import Path

import pandas as pd
import pytest

from app.services.excel_importer import (
    E_RESTAURANT_ID,
    TIP_RESTAURANT_ID,
    ParsedMeal,
    _is_block_boundary,
    _meal_type,
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


def test_month_wrap_workbook_parses_aug31_to_sep5() -> None:
    """월 경계 주(31일, 9/1일, 2일…)는 8/31~9/5로 파싱되고 보정되지 않는다."""
    parsed = _fixture_meals("meal_2026_08_31.xlsx", dt.date(2026, 8, 31))

    dates = sorted({m.date for m in parsed})
    assert dates[0] == dt.date(2026, 8, 31)
    assert dates[-1] == dt.date(2026, 9, 5)
    assert len(dates) == 6
    assert any(
        m.meal_type == "breakfast" and m.restaurant_id == TIP_RESTAURANT_ID
        for m in parsed
    )


def test_header_year_wrap() -> None:
    """12월 말 뒤에 일(日)이 줄면 다음 해 1월로 넘어간다."""
    cells = ["12월", "29일", "30일", "31일", "1일", "2일"]
    dates = parse_header_dates(cells, dt.date(2026, 12, 29))
    assert dates[4] == dt.date(2027, 1, 1)
    assert dates[5] == dt.date(2027, 1, 2)


def test_header_explicit_month_conflict_rejected() -> None:
    """명시 월 표기와 충돌하는 오기는 보정하지 않고 거부한다."""
    cells = ["8월", "28일", "29일", "9/20일", "31일", "9/1일"]
    assert parse_header_dates(cells, dt.date(2026, 8, 28)) == {}


def test_meal_type_breakfast_labels() -> None:
    """Breakfast labels match by '조식' prefix or '아침' anywhere."""
    for label in ("천원의 아침밥", "천원의아침밥(8:30~10:00)", "아침", "아침식사"):
        assert _meal_type(label) == "breakfast"


def test_is_block_boundary_time_rows() -> None:
    """Time rows are not boundaries, but meal labels with times and notes are."""
    for label in ("8:30~10:00", "(8:30~10:00)", "오전 8:30~10:00", ""):
        assert not _is_block_boundary(label)
    for label in ("중식 11:30~13:30", "중식", "**상기 식단은"):
        assert _is_block_boundary(label)


def test_parenthesized_time_row_does_not_cut_breakfast_menu() -> None:
    """A '(8:30~10:00)' row under the label keeps later menu rows in the block."""
    df = workbook()
    df.iloc[3, 0] = "(8:30~10:00)"
    df.iloc[3, 2] = "A2"
    parsed = parse_weekly_menus(df, dt.date(2026, 8, 24))
    tip = next(
        meal
        for meal in parsed
        if meal.restaurant_id == TIP_RESTAURANT_ID
        and meal.meal_type == "breakfast"
        and meal.date == dt.date(2026, 8, 25)
    )
    assert tip.menu == ["A", "A2"]


def test_breakfast_note_below_dinner_is_not_a_label() -> None:
    """A '아침...' note row after dinner adds no breakfast and ends dinner."""
    df = workbook()
    df.iloc[6, 0] = "아침은 8시부터 운영"
    df.iloc[6, 1] = "note"
    parsed = parse_weekly_menus(df, dt.date(2026, 8, 24))
    tip = [m for m in parsed if m.restaurant_id == TIP_RESTAURANT_ID]
    assert len([m for m in tip if m.meal_type == "breakfast"]) == 6
    dinner = next(m for m in tip if m.meal_type == "dinner")
    assert dinner.menu == ["TIP 저"]


def test_header_missing_column_keeps_resolved_dates() -> None:
    """빠진 날짜 열(24일) 뒤의 25·26일은 보정 없이 그대로 쓴다."""
    cells = ["9월", "21일", "22일", "23일", "25일", "26일"]
    dates = parse_header_dates(cells, dt.date(2026, 9, 21))
    assert dates == {
        1: dt.date(2026, 9, 21),
        2: dt.date(2026, 9, 22),
        3: dt.date(2026, 9, 23),
        4: dt.date(2026, 9, 25),
        5: dt.date(2026, 9, 26),
    }


def test_header_reversed_order_rejected() -> None:
    """순서가 뒤집힌 헤더는 보정하지 않고 거부한다."""
    cells = ["9월", "21일", "22일", "23일", "26일", "25일"]
    assert parse_header_dates(cells, dt.date(2026, 9, 21)) == {}


def test_header_missing_leading_column_keeps_dates() -> None:
    """주 앞쪽에 빠진 열이 있어도 해석한 날짜를 그대로 쓴다."""
    cells = ["9월", "21일", "22일", "24일", "25일", "26일"]
    dates = parse_header_dates(cells, dt.date(2026, 9, 21))
    assert list(dates.values()) == [dt.date(2026, 9, d) for d in (21, 22, 24, 25, 26)]
    wrap = parse_header_dates(
        ["9월", "28일", "29일", "1일", "2일", "3일"], dt.date(2026, 9, 28)
    )
    assert wrap[3] == dt.date(2026, 10, 1)
    assert wrap[5] == dt.date(2026, 10, 3)


def test_unfamiliar_timed_label_is_boundary() -> None:
    """시간이 붙은 낯선 끼니 라벨은 경계이고 끼니로는 인식하지 않는다."""
    assert _is_block_boundary("천원의 저녁밥 17:00~18:50")
    assert not _is_block_boundary("8:30~ 10:00")
    assert _meal_type("※ 점심 메뉴는 변경될 수 있음") is None


def test_second_breakfast_label_is_not_a_label() -> None:
    """첫 조식 라벨 뒤의 '아침' 행은 라벨이 아니라 앞 조식 블록의 일부다."""
    df = workbook()
    df.iloc[3, 0] = "천원의 아침밥"
    df.iloc[3, 2] = "A2"
    parsed = parse_weekly_menus(df, dt.date(2026, 8, 24))
    tip = [
        m
        for m in parsed
        if m.restaurant_id == TIP_RESTAURANT_ID and m.meal_type == "breakfast"
    ]
    assert len(tip) == 6
    assert next(m for m in tip if m.date == dt.date(2026, 8, 25)).menu == ["A"]


def _d(*pairs: tuple[int, int, int]) -> list[dt.date]:
    return [dt.date(*pair) for pair in pairs]


_W = dt.date(2026, 9, 21)
HEADER_CASES = [
    # (헤더 월, 날짜 셀, today, 기대 날짜 목록 또는 None=거부)
    (
        "9월",
        ["21일", "22일", "24일", "25일", "26일"],
        _W,
        _d((2026, 9, 21), (2026, 9, 22), (2026, 9, 24), (2026, 9, 25), (2026, 9, 26)),
    ),
    (
        "9월",
        ["21일", "23일", "24일", "25일", "26일"],
        _W,
        _d((2026, 9, 21), (2026, 9, 23), (2026, 9, 24), (2026, 9, 25), (2026, 9, 26)),
    ),
    (
        "9월",
        ["28일", "29일", "1일", "2일", "3일"],
        dt.date(2026, 9, 28),
        _d((2026, 9, 28), (2026, 9, 29), (2026, 10, 1), (2026, 10, 2), (2026, 10, 3)),
    ),
    (
        "9월",
        ["30일", "1일", "2일", "3일"],
        dt.date(2026, 9, 30),
        _d((2026, 9, 30), (2026, 10, 1), (2026, 10, 2), (2026, 10, 3)),
    ),
    (
        "10월",
        ["31일", "2일", "3일", "4일"],
        dt.date(2026, 10, 31),
        _d((2026, 10, 31), (2026, 11, 2), (2026, 11, 3), (2026, 11, 4)),
    ),
    (
        "12월",
        ["29일", "30일", "31일", "1일", "2일"],
        dt.date(2026, 12, 29),
        _d((2026, 12, 29), (2026, 12, 30), (2026, 12, 31), (2027, 1, 1), (2027, 1, 2)),
    ),
    (
        "12월",
        ["29일", "30일", "31일", "1일", "2일"],
        dt.date(2027, 1, 2),
        _d((2026, 12, 29), (2026, 12, 30), (2026, 12, 31), (2027, 1, 1), (2027, 1, 2)),
    ),
    (
        "2월",
        ["28일", "29일", "1일"],
        dt.date(2028, 2, 28),
        _d((2028, 2, 28), (2028, 2, 29), (2028, 3, 1)),
    ),
    ("2월", ["28일", "29일", "1일"], dt.date(2026, 2, 28), None),
    ("9월", ["26일", "22일", "23일", "24일"], _W, None),
    ("9월", ["21일", "21일", "21일", "24일"], _W, None),
    ("9월", ["21일"], _W, _d((2026, 9, 21))),
    ("9월", ["", "메뉴"], _W, None),
    (
        "9월",
        [f"{day}일" for day in range(21, 28)],
        _W,
        _d(*[(2026, 9, day) for day in range(21, 28)]),
    ),
    ("9월", [f"{day}일" for day in range(21, 29)], _W, None),
    (
        "9월",
        ["21일", "21일(화)", "23일"],
        _W,
        _d((2026, 9, 21), (2026, 9, 22), (2026, 9, 23)),
    ),
    ("9월", ["21일", "21일(월)", "25일"], _W, None),
    (
        "9월",
        ["21일", "22일", "23일", "23일(수)"],
        _W,
        _d((2026, 9, 21), (2026, 9, 22), (2026, 9, 23), (2026, 9, 24)),
    ),
    ("9월", ["23일", "25일", "25일"], _W, None),
    (
        "9월",
        ["24일", "25일", "26일", "26일", "28일", "29일"],
        _W,
        _d(
            (2026, 9, 24),
            (2026, 9, 25),
            (2026, 9, 26),
            (2026, 9, 27),
            (2026, 9, 28),
            (2026, 9, 29),
        ),
    ),
    ("9월", ["9/1일", "2일"], dt.date(2026, 9, 1), _d((2026, 9, 1), (2026, 9, 2))),
    ("9월", ["10 일", "11 일"], dt.date(2026, 9, 10), _d((2026, 9, 10), (2026, 9, 11))),
    (
        "9월",
        ["14일\n(월)", "15일\n(화)"],
        dt.date(2026, 9, 14),
        _d((2026, 9, 14), (2026, 9, 15)),
    ),
    (
        "9월",
        [" 14일 ", " 15일 "],
        dt.date(2026, 9, 14),
        _d((2026, 9, 14), (2026, 9, 15)),
    ),
]


@pytest.mark.parametrize(("month", "cells", "today", "expected"), HEADER_CASES)
def test_header_boundary_cases(
    month: str, cells: list[str], today: dt.date, expected: list[dt.date] | None
) -> None:
    """월·연·윤년 경계, 빠진 열, 오기, 표기 변형을 표로 검증한다."""
    dates = parse_header_dates([month, *cells], today)
    assert list(dates.values()) == (expected or [])


@pytest.mark.parametrize("label", ["조 식", "조식\n8:30~10:00", "천원의\n아침밥"])
def test_breakfast_label_variants(label: str) -> None:
    """공백·시간이 붙은 조식 라벨도 TIP 조식 6일치로 인식한다."""
    df = workbook()
    df.iloc[2, 0] = label
    parsed = parse_weekly_menus(df, dt.date(2026, 8, 24))
    tip = [m for m in parsed if m.restaurant_id == 1 and m.meal_type == "breakfast"]
    assert len(tip) == 6
    assert tip[0].menu == ["미운영"]


@pytest.mark.parametrize(
    "time_row",
    ["08:30~10:00", "8:30-10:00", "(8:30~10:00)", "오전 8:30 ~ 10:00"],
)
def test_time_row_variants_keep_menu(time_row: str) -> None:
    """시간 행 표기가 달라도 조식 블록을 끊지 않는다."""
    df = workbook()
    df.iloc[3, 0] = time_row
    df.iloc[3, 2] = "A2"
    parsed = parse_weekly_menus(df, dt.date(2026, 8, 24))
    tip = next(
        m
        for m in parsed
        if m.restaurant_id == 1
        and m.meal_type == "breakfast"
        and m.date == dt.date(2026, 8, 25)
    )
    assert tip.menu == ["A", "A2"]


@pytest.mark.parametrize(
    "note", ["※ 점심 메뉴는 변경될 수 있음", "※ 석식은 변경될 수 있음", "*복수메뉴*"]
)
def test_first_column_notes_do_not_become_meals(note: str) -> None:
    """A열 주석 행은 끼니가 되지 않고 석식 블록만 끝낸다."""
    df = workbook()
    df.iloc[6, 0] = note
    df.iloc[6, 1] = "note"
    parsed = parse_weekly_menus(df, dt.date(2026, 8, 24))
    tip = [m for m in parsed if m.restaurant_id == 1]
    assert next(m for m in tip if m.meal_type == "dinner").menu == ["TIP 저"]
    assert next(m for m in tip if m.meal_type == "lunch").menu == ["TIP 월"]
    assert len(tip) == 18


def test_breakfast_only_block() -> None:
    """조식만 있는 TIP 블록도 조식만 파싱한다."""
    df = workbook()
    df.iloc[4:6, :] = ""
    parsed = parse_weekly_menus(df, dt.date(2026, 8, 24))
    assert {m.meal_type for m in parsed if m.restaurant_id == 1} == {"breakfast"}


def test_duplicate_meal_label_rejects_block() -> None:
    """같은 끼니 라벨이 두 번이면 덮어쓰기 대신 파일 전체를 거부한다."""
    df = workbook()
    df.iloc[5, 0] = "중식"
    assert parse_weekly_menus(df, dt.date(2026, 8, 24)) == []


def test_mismatched_restaurant_dates_reject_workbook() -> None:
    """TIP과 E동의 날짜 집합이 다르면 파일 전체를 거부한다."""
    df = workbook()
    df.iloc[8, 6] = "30일"
    assert parse_weekly_menus(df, dt.date(2026, 8, 24)) == []
