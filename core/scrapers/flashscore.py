from .base import BaseScraper


class FlashscoreScraper(BaseScraper):
    async def scrape(self, url):
        page = await self.context.new_page()
        await page.goto(url)
        # Logic specific to OddsPortal
        data = await page.locator(".eventRow").all_inner_texts()
        await page.close()
        return data
