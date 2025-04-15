from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.services.crawler_service import download_and_save_excel_to_db

scheduler = AsyncIOScheduler()


def start_scheduler():
    scheduler.add_job(
        download_and_save_excel_to_db,
        trigger="cron",
        hour=22,
        minute=0,
        timezone="Asia/Seoul",
        id="meal_excel_sync",
    )
    scheduler.start()


def stop_scheduler():
    scheduler.shutdown()
