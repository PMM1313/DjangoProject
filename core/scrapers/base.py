class BaseScraper:
    def __init__(self, browser_context):
        self.context = browser_context

    async def scrape(self, url):
        raise NotImplementedError("Each scraper must implement the scrape method")