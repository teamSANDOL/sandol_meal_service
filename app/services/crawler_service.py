import os

from app.config import Config
from app.database import AsyncSessionLocal
from app.services.ibook_downloader import BookDownloader
from app.services.excel_importer import (
    ExcelMealImporter,
)


async def download_and_save_excel_to_db():
    downloader = BookDownloader()
    await downloader.get_file(os.path.join(Config.TMP_DIR, "data.xlsx"))

    importer = ExcelMealImporter()
    async with AsyncSessionLocal() as session:
        await importer.insert_to_db(session)
