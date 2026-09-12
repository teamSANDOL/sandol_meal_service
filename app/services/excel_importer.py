"""Parse and import the university's weekly meal workbook."""

from __future__ import annotations

import datetime as dt
import os
import re
from dataclasses import dataclass
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Config, logger
from app.models.meals import MealType
from app.utils.meals import upsert_meal

EXCEL_PATH = os.path.join(Config.TMP_DIR, "data.xlsx")
TIP_RESTAURANT_ID = int(Config.TIP_RESTAURANT_ID)
E_RESTAURANT_ID = int(Config.E_RESTAURANT_ID)
MEAL_LABELS = ("조식", "중식", "석식")
_MONTH_RE = re.compile(r"^\s*(\d{1,2})월\s*$")
_SLASH_DATE_RE = re.compile(r"(\d{1,2})\s*/\s*(\d{1,2})")


@dataclass(frozen=True)
class ParsedMeal:
    """One non-empty restaurant/meal/date/menu tuple from the workbook."""

    restaurant_id: int
    meal_type: str
    date: dt.date
    menu: list[str]


@dataclass(frozen=True)
class _ParsedBlock:
    """Validated meals and header dates from one required restaurant block."""

    meals: list[ParsedMeal]
    dates: frozenset[dt.date]


def _cell_text(value: Any) -> str:
    """Return a trimmed cell string, treating pandas NaN as empty."""
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def clean_menu(menu_list: list[Any]) -> list[str]:
    """Remove empty and workbook decoration rows while preserving status text."""
    cleaned: list[str] = []
    for item in menu_list:
        value = _cell_text(item)
        if not value or value == "*복수메뉴*":
            continue
        if value.startswith("★") or value.startswith("**"):
            continue
        cleaned.append(value)
    return cleaned


def _nearest_year(month: int, day: int, today: dt.date) -> int | None:
    """Choose the year nearest to today for a month/day pair."""
    candidates: list[dt.date] = []
    for year in (today.year - 1, today.year, today.year + 1):
        try:
            candidates.append(dt.date(year, month, day))
        except ValueError:
            continue
    if not candidates:
        return None
    return min(candidates, key=lambda value: abs(value - today)).year


def _header_day(value: Any, expected: dt.date) -> bool:
    """Check a day header against the date inferred from the first column."""
    text = _cell_text(value)
    if not text:
        return False
    slash_match = _SLASH_DATE_RE.search(text)
    if slash_match:
        return (
            int(slash_match.group(1)) == expected.month
            and int(slash_match.group(2)) == expected.day
        )
    day_match = re.search(r"(\d{1,2})\s*일", text)
    return bool(day_match and int(day_match.group(1)) == expected.day)


def parse_header_dates(cells: list[Any], today: dt.date) -> dict[int, dt.date]:
    """Convert a month/day header row into validated column dates."""
    month_match = _MONTH_RE.match(_cell_text(cells[0])) if cells else None
    if not month_match:
        return {}
    header_month = int(month_match.group(1))

    first_column: int | None = None
    anchor: dt.date | None = None
    for column, value in enumerate(cells[1:], start=1):
        text = _cell_text(value)
        day_match = re.search(r"(\d{1,2})\s*일", text)
        if not day_match:
            continue
        slash_match = _SLASH_DATE_RE.search(text)
        first_month = int(slash_match.group(1)) if slash_match else header_month
        first_day = int(day_match.group(1))
        first_year = _nearest_year(first_month, first_day, today)
        if first_year is None:
            return {}
        first_column = column
        anchor = dt.date(first_year, first_month, first_day)
        break
    if first_column is None or anchor is None:
        return {}

    dates: dict[int, dt.date] = {}
    for column, value in enumerate(cells[1:], start=1):
        expected = anchor + dt.timedelta(days=column - first_column)
        if _header_day(value, expected):
            dates[column] = expected
    return dates


def _block_bounds(df: pd.DataFrame) -> tuple[tuple[int, int], tuple[int, int]] | None:
    """Split the workbook into TIP and E-dong row ranges."""
    first_column = [_cell_text(value) for value in df.iloc[:, 0].tolist()]
    tip_start = next(
        (index for index, value in enumerate(first_column) if "TIP" in value),
        None,
    )
    e_start = next(
        (index for index, value in enumerate(first_column) if "E동" in value),
        None,
    )
    if tip_start is None or e_start is None or tip_start >= e_start:
        return None
    return (tip_start, e_start), (e_start, len(first_column))


def _parse_block(
    df: pd.DataFrame,
    bounds: tuple[int, int],
    restaurant_id: int,
    today: dt.date,
) -> _ParsedBlock | None:
    """Parse meal-label blocks within one restaurant section."""
    start, end = bounds
    header_row = next(
        (
            row
            for row in range(start, end)
            if _MONTH_RE.match(_cell_text(df.iloc[row, 0]))
        ),
        None,
    )
    if header_row is None:
        return None
    dates = parse_header_dates(df.iloc[header_row, :].tolist(), today)
    if not dates:
        return None

    label_rows = [
        row
        for row in range(header_row + 1, end)
        if any(_cell_text(df.iloc[row, 0]).startswith(label) for label in MEAL_LABELS)
    ]
    if not label_rows:
        return None

    parsed: list[ParsedMeal] = []
    for label_row in label_rows:
        label_text = _cell_text(df.iloc[label_row, 0])
        meal_label = next(
            label for label in MEAL_LABELS if label_text.startswith(label)
        )
        next_label_or_boundary = next(
            (row for row in range(label_row + 1, end) if _cell_text(df.iloc[row, 0])),
            end,
        )
        meal_type = {"조식": "breakfast", "중식": "lunch", "석식": "dinner"}[meal_label]
        for column, meal_date in dates.items():
            menu = clean_menu(
                df.iloc[label_row:next_label_or_boundary, column].tolist()
            )
            if menu:
                parsed.append(
                    ParsedMeal(
                        restaurant_id=restaurant_id,
                        meal_type=meal_type,
                        date=meal_date,
                        menu=menu,
                    )
                )
    if not parsed:
        return None
    return _ParsedBlock(meals=parsed, dates=frozenset(dates.values()))


def parse_weekly_menus(df: pd.DataFrame, today: dt.date) -> list[ParsedMeal]:
    """Parse a workbook only when both required restaurant blocks are valid."""
    bounds = _block_bounds(df)
    if bounds is None:
        return []
    tip_bounds, e_bounds = bounds
    tip_block = _parse_block(df, tip_bounds, TIP_RESTAURANT_ID, today)
    e_block = _parse_block(df, e_bounds, E_RESTAURANT_ID, today)
    if tip_block is None or e_block is None:
        logger.error("[엑셀 파싱] TIP 또는 E동 필수 식당 블록 파싱 실패")
        return []
    if tip_block.dates != e_block.dates:
        logger.error(
            "[엑셀 파싱] 식당별 날짜 불일치: TIP=%s E동=%s",
            sorted(tip_block.dates),
            sorted(e_block.dates),
        )
        return []
    return tip_block.meals + e_block.meals


class ExcelMealImporter:
    """Read a workbook and upsert all non-empty weekly meal cells."""

    def __init__(self, path: str = EXCEL_PATH) -> None:
        """Load the workbook without consuming its first row as headers."""
        self.path = path
        self.df = pd.read_excel(path, header=None)

    def parse(self, today: dt.date | None = None) -> list[ParsedMeal]:
        """Return parsed meals without touching the database."""
        parse_date = today or dt.datetime.now(tz=Config.TZ).date()
        return parse_weekly_menus(self.df, parse_date)

    async def insert_to_db(
        self,
        db: AsyncSession,
        file_modified: dt.datetime | None = None,
    ) -> list[ParsedMeal]:
        """Upsert parsed meals and commit once; return the parsed records."""
        del file_modified
        parsed = self.parse()
        if not parsed:
            logger.error("[엑셀→DB] 날짜 또는 식사 블록 파싱 실패: %s", self.path)
            return []

        await self.insert_parsed_to_db(db, parsed)
        return parsed

    async def insert_parsed_to_db(
        self,
        db: AsyncSession,
        parsed: list[ParsedMeal],
    ) -> None:
        """Upsert an already parsed workbook and commit once."""
        if not parsed:
            return

        result = await db.execute(select(MealType))
        meal_type_ids = {meal_type.name: meal_type.id for meal_type in result.scalars()}
        for meal in parsed:
            meal_type_id = meal_type_ids.get(meal.meal_type)
            if meal_type_id is None:
                logger.error("[엑셀→DB] 알 수 없는 식사 유형: %s", meal.meal_type)
                continue
            await upsert_meal(
                db,
                restaurant_id=meal.restaurant_id,
                meal_type_id=meal_type_id,
                menu=meal.menu,
                date=meal.date,
            )

        await db.commit()
        logger.info(
            "[엑셀→DB] %d건 반영 (%s ~ %s)",
            len(parsed),
            min(meal.date for meal in parsed),
            max(meal.date for meal in parsed),
        )
