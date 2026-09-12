"""APScheduler entry point for meal workbook synchronization."""

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import Config, logger
from app.services.crawler_service import download_and_save_excel_to_db

scheduler = AsyncIOScheduler(timezone=Config.TZ)


async def poll_meal_excel() -> None:
    """Run one discovery/watch synchronization tick."""
    logger.info("[meal_excel_sync] synchronization tick")
    await download_and_save_excel_to_db()


def start_scheduler() -> None:
    """Start the single 30-minute cron job."""
    scheduler.add_job(
        poll_meal_excel,
        trigger="cron",
        minute="0,30",
        timezone=Config.TZ,
        id="meal_excel_sync",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    scheduler.start()


def stop_scheduler() -> None:
    """Stop the scheduler when the application shuts down."""
    scheduler.shutdown()
