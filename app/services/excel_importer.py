import os
import pandas as pd
import datetime as dt
from pytz import timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.meals import Meal, MealType
from app.config import Config, logger

KST = timezone("Asia/Seoul")
EXCEL_PATH = os.path.join(Config.TMP_DIR, "data.xlsx")

TIP_RESTAURANT_ID = int(Config.TIP_RESTAURANT_ID)
E_RESTAURANT_ID = int(Config.E_RESTAURANT_ID)


def clean_menu(menu_list):
    return [
        item
        for item in menu_list
        if isinstance(item, str) and item.strip() and item != "*복수메뉴*"
    ]


class ExcelMealImporter:
    def __init__(self):
        self.df = pd.read_excel(EXCEL_PATH)

    def _get_weekday(self):
        return dt.datetime.now(tz=KST).isoweekday()

    def extract_tip_menus(self):
        weekday = self._get_weekday()
        lunch = clean_menu(self.df.iloc[6:12, weekday].tolist())
        dinner = clean_menu(self.df.iloc[13:19, weekday].tolist())
        return lunch, dinner

    def extract_e_menus(self):
        weekday = self._get_weekday()
        lunch = clean_menu(self.df.iloc[22:29, weekday].tolist())
        dinner = clean_menu(self.df.iloc[30:37, weekday].tolist())
        return lunch, dinner

    async def insert_to_db(self, db: AsyncSession):
        tip_lunch, tip_dinner = self.extract_tip_menus()
        e_lunch, e_dinner = self.extract_e_menus()

        # MealType 이름-아이디 매핑
        result = await db.execute(select(MealType))
        meal_type_dict = {mt.name: mt.id for mt in result.scalars()}

        now = dt.datetime.now(tz=KST)

        def make_meal_entries(restaurant_id, lunch, dinner):
            return [
                Meal(
                    restaurant_id=restaurant_id,
                    meal_type_id=meal_type_dict["lunch"],
                    menu=lunch,
                    registered_at=now,
                ),
                Meal(
                    restaurant_id=restaurant_id,
                    meal_type_id=meal_type_dict["dinner"],
                    menu=dinner,
                    registered_at=now,
                ),
            ]

        meals = make_meal_entries(
            TIP_RESTAURANT_ID, tip_lunch, tip_dinner
        ) + make_meal_entries(E_RESTAURANT_ID, e_lunch, e_dinner)

        db.add_all(meals)
        await db.commit()

        logger.info(f"[엑셀→DB] TIP/E동 학식 총 {len(meals)}개 등록 완료")
