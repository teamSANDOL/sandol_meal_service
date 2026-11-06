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
_MONTH_END_DAY = 28
_TIME_ONLY_RE = re.compile(r"\d{1,2}:\d{2}|오전|오후|[()~\-:.]")
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


def _meal_type(label: str) -> str | None:
    """Map a first-column label to a meal type, ignoring whitespace/newlines.

    '조식'으로 시작하거나 '아침'을 포함하면(예: '천원의 아침밥') 조식이다.
    주석 행 오인은 호출부(_parse_block)가 위치로 걸러낸다.
    """
    compact = re.sub(r"\s+", "", label)
    if compact.startswith("조식") or "아침" in compact:
        return "breakfast"
    if compact.startswith("중식") or "점심" in compact:
        return "lunch"
    if compact.startswith("석식") or "저녁" in compact:
        return "dinner"
    return None


def _is_block_boundary(label: str) -> bool:
    """Return True for a non-empty first cell that starts a new section.

    끼니 라벨은 시간이 붙어 있어도('중식 11:30~13:30') 경계이고, 라벨 아래로
    밀려난 시간 행('8:30~ 10:00', '(8:30~10:00)', '오전 8:30~10:00')은 아니다.
    """
    compact = re.sub(r"\s+", "", label)
    if not compact:
        return False
    return _meal_type(label) is not None or bool(_TIME_ONLY_RE.sub("", compact))


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


def _resolve_header_candidates(
    cells: list[Any], header_month: int, today: dt.date
) -> list[tuple[int, dt.date]]:
    """Resolve each dated header cell to a date, tracking month/year rollover.

    'M/D' 표기는 그 월을 우선하고, 말일 뒤에 일(日)이 줄면 다음 달로 본다.
    시트 상단의 '8월'은 시작 월 힌트일 뿐이다. 해석 불가면 빈 리스트.
    """
    candidates: list[tuple[int, dt.date]] = []
    month = header_month
    year: int | None = None
    prev_day: int | None = None
    for column, value in enumerate(cells[1:], start=1):
        text = _cell_text(value)
        day_match = re.search(r"(\d{1,2})\s*일", text)
        if not day_match:
            continue
        day = int(day_match.group(1))
        slash_match = _SLASH_DATE_RE.search(text)
        if slash_match:
            new_month = int(slash_match.group(1))
        elif prev_day is not None and prev_day >= _MONTH_END_DAY and day < prev_day:
            # 31 -> 1처럼 말일 뒤에 일(日)이 줄면 다음 달로 넘어간 것이다.
            new_month = month % 12 + 1
        else:
            new_month = month
        if year is None:
            year = _nearest_year(new_month, day, today)
            if year is None:
                return []
        elif new_month < month:
            year += 1
        month, prev_day = new_month, day
        try:
            candidates.append((column, dt.date(year, month, day)))
        except ValueError:
            return []
    return candidates


def parse_header_dates(
    cells: list[Any], today: dt.date, block: str = ""
) -> dict[int, dt.date]:
    """Convert a month/day header row into column dates.

    날짜가 적힌 열 중 과반이 같은 주(첫 열 기준 연속 날짜)와 일치해야 하며,
    일치하지 않는 헤더는 같은 주 안에서 순서가 맞으면(빈 날) 그대로 쓰고,
    아니면(오기) 열 위치로 계산한 날짜로 보정한다. 최종 날짜는 엄격 증가해야 한다.
    과반이 일치하지 않으면 빈 dict를 반환해 파일을 거부한다.
    """
    month_match = _MONTH_RE.match(_cell_text(cells[0])) if cells else None
    if not month_match:
        return {}
    header_month = int(month_match.group(1))

    candidates = _resolve_header_candidates(cells, header_month, today)
    if not candidates:
        return {}

    def matches(anchor: tuple[int, dt.date]) -> list[int]:
        column0, date0 = anchor
        return [
            column
            for column, date in candidates
            if date == date0 + dt.timedelta(days=column - column0)
        ]

    best = max(candidates, key=lambda item: len(matches(item)))
    matched = matches(best)
    if len(matched) * 2 <= len(candidates):
        return {}

    week_start = best[1] + dt.timedelta(days=candidates[0][0] - best[0])
    week_end = week_start + dt.timedelta(days=6)
    dates: dict[int, dt.date] = {}
    for index, (column, resolved) in enumerate(candidates):
        if column not in matched:
            expected = best[1] + dt.timedelta(days=column - best[0])
            previous = max(dates.values(), default=dt.date.min)
            upcoming = (
                candidates[index + 1][1] if index + 1 < len(candidates) else dt.date.max
            )
            if previous < resolved < upcoming and week_start <= resolved <= week_end:
                # 빈 날이 있는 주(예: 24일 열 없음)는 해석한 날짜를 그대로 쓴다.
                dates[column] = resolved
                continue
            if (expected.year, expected.month) != (resolved.year, resolved.month):
                logger.error(
                    "[엑셀 파싱] 헤더 월 충돌로 거부 (%s): '%s' vs %s",
                    block,
                    _cell_text(cells[column]),
                    expected,
                )
                return {}
            logger.warning(
                "[엑셀 파싱] 헤더 날짜 보정 (%s): '%s' -> %s",
                block,
                _cell_text(cells[column]),
                expected,
            )
            dates[column] = expected
        else:
            dates[column] = resolved
    values = list(dates.values())
    if values != sorted(set(values)):
        return {}
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
    dates = parse_header_dates(
        df.iloc[header_row, :].tolist(), today, f"restaurant={restaurant_id}"
    )
    if not dates:
        return None

    # 조식 라벨은 첫 중식/석식 라벨 앞의 첫 번째 것만 인정한다(주석 행 오인 방지).
    typed_rows = [
        (row, _meal_type(_cell_text(df.iloc[row, 0])))
        for row in range(header_row + 1, end)
    ]
    first_later_meal = next(
        (row for row, kind in typed_rows if kind in ("lunch", "dinner")), end
    )
    first_breakfast = next(
        (row for row, kind in typed_rows if kind == "breakfast"), end
    )
    labels = [
        (row, kind)
        for row, kind in typed_rows
        if kind is not None
        and (kind != "breakfast" or (row == first_breakfast < first_later_meal))
    ]
    if not labels:
        return None

    parsed: list[ParsedMeal] = []
    for label_row, meal_type in labels:
        next_label_or_boundary = next(
            (
                row
                for row in range(label_row + 1, end)
                if _is_block_boundary(_cell_text(df.iloc[row, 0]))
            ),
            end,
        )
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
