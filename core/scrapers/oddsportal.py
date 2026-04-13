from .base import BaseScraper


class OddsPortalScraper(BaseScraper):

    async def scrape(self, url):

        page = await self.context.new_page()

        try:
            # 1. Navigate to the URL
            await page.goto(url)

            # 2. WAIT HERE before trying to find data
            # This pauses the code until the element exists and is visible
            # If it doesn't show up in 15s, it throws an error that Celery catches
            print(f"Waiting for odds table on {url}...")
            await page.wait_for_selector(".eventRow", state="visible", timeout=15000)

            # Try to click 'Accept' if the button exists, otherwise just keep going
            cookie_button = page.locator("button:has-text('Accept')")
            if await cookie_button.is_visible():
                await cookie_button.click()

            # 3. Now scrape the data
            data = await page.locator(".eventRow").all_inner_texts()
            return data

        finally:
            # This runs even if the wait_for_selector fails (prevents hanging browsers)
            await page.close()
