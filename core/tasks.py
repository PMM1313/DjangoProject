import asyncio
from celery import shared_task
from playwright.async_api import async_playwright
from core.scrapers.oddsportal import OddsPortalScraper
from core.scrapers.flashscore import FlashscoreScraper


@shared_task(bind=True, max_retries=3)
def run_universal_scrape(self, source_name, url):
    try:
        return asyncio.run(execute_scrape(source_name, url))
    except Exception as exc:
        # If the page didn't load, wait 10 mins and try again
        raise self.retry(exc=exc, countdown=600)


async def execute_scrape(source_name, url):
    # 1. Map names to classes
    scrapers = {
        'oddsportal': OddsPortalScraper,
        'flashscore': FlashscoreScraper,
    }

    # 2. Start Playwright and create the 'context'
    async with async_playwright() as p:

        browser = await p.chromium.launch(headless=False, slow_mo=500)

        # This is where 'context' is created!
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 720},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

        scraper_class = scrapers.get(source_name)

        if not scraper_class:
            await browser.close()
            return f"Scraper for {source_name} not found."

        # 3. Initialize the scraper with the context and run it
        scraper_instance = scraper_class(context)
        data = await scraper_instance.scrape(url)

        await browser.close()

        # 4. Save to Django Database (Remember to use sync_to_async if needed)
        # print(data) 
        return f"Successfully scraped {source_name}"