import os
import requests
import json
from dotenv import load_dotenv

load_dotenv()


def scrape_odds_portal():
    TOKEN = os.getenv("BROWSERLESS_TOKEN")

    url = f"https://production-sfo.browserless.io/function?token={TOKEN}&timeout=60000"

    code = r"""
    export default async function ({ page }) {
      function sleep(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
      }

      async function humanScroll(page, totalDistance = 1200) {
        let scrolled = 0;

        while (scrolled < totalDistance) {
          const step = Math.floor(180 + Math.random() * 220);
          await page.evaluate((y) => window.scrollBy(0, y), step);
          scrolled += step;

          const pause = Math.floor(250 + Math.random() * 500);
          await sleep(pause);
        }
      }

      async function waitForRowsToSettle(page, selector, checks = 3, delay = 700) {
        let lastCount = -1;
        let stable = 0;

        while (stable < checks) {
          const count = await page.$$eval(selector, els => els.length);

          if (count === lastCount) {
            stable += 1;
          } else {
            stable = 0;
            lastCount = count;
          }

          await sleep(delay);
        }

        return lastCount;
      }

      async function isSentinelInView(page) {
        return await page.$eval(
          '[data-testid="next-matches-scroll-sentinel"]',
          (el) => {
            const rect = el.getBoundingClientRect();
            const viewHeight = window.innerHeight || document.documentElement.clientHeight;
            return rect.top < viewHeight && rect.bottom >= 0;
          }
        );
      }

      await page.goto('https://www.oddsportal.com/football/', {
        waitUntil: 'domcontentloaded',
        timeout: 120000,
      });

      await page.waitForSelector('[data-testid="game-row"]', { timeout: 60000 });

      const maxRounds = 10;

      for (let i = 0; i < maxRounds; i++) {
        const inViewBefore = await isSentinelInView(page);
        if (inViewBefore) break;

        await humanScroll(page, 1000 + Math.floor(Math.random() * 800));
        await waitForRowsToSettle(page, '[data-testid="game-row"]', 3, 700);

        const inViewAfter = await isSentinelInView(page);
        if (inViewAfter) break;
      }

      const fixtures = await page.evaluate(() => {
        const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();

        const normalizeStatus = (raw) => {
          const value = clean(raw);
          if (!value) return { status: 'Unknown', startTime: null };

          if (/^\d{1,2}:\d{2}$/.test(value)) {
            return { status: 'Not Started', startTime: value };
          }

          const upper = value.toUpperCase();

          if (upper === 'FIN' || /finished/i.test(value)) {
            return { status: 'Finished', startTime: null };
          }
          if (/live/i.test(value) || /^\d+'$/.test(value) || /^\d+\+\d+'$/.test(value)) {
            return { status: 'Live', startTime: null };
          }
          if (/cancel/i.test(value)) {
            return { status: 'Canceled', startTime: null };
          }
          if (/suspend/i.test(value)) {
            return { status: 'Suspended', startTime: null };
          }
          if (/postpon/i.test(value)) {
            return { status: 'Postponed', startTime: null };
          }
          if (/abandon/i.test(value)) {
            return { status: 'Abandoned', startTime: null };
          }
          if (/interrupt/i.test(value)) {
            return { status: 'Interrupted', startTime: null };
          }

          return { status: value, startTime: null };
        };

        const root = document.querySelector('[data-testid="next-matches-list-pending-frame"]') || document.body;
        const all = Array.from(root.querySelectorAll('[data-testid="sport-country-league-item"], [data-testid="game-row"]'));

        let currentCountry = null;
        let currentLeague = null;
        const fixtures = [];

        for (const el of all) {
          const testid = el.getAttribute('data-testid');

          if (testid === 'sport-country-league-item') {
            currentCountry = clean(
              el.querySelector('[data-testid="header-country-item"] p')?.textContent
            );
            currentLeague = clean(
              el.querySelector('[data-testid="header-tournament-item"] p')?.textContent
            );
            continue;
          }

          if (testid === 'game-row') {
            const participants = el.querySelectorAll('[data-testid="participant-name"]');
            const homeTeam = clean(participants[0]?.textContent);
            const awayTeam = clean(participants[1]?.textContent);

            const rawTimeStatus = clean(
              el.querySelector('[data-testid="time-item"]')?.textContent
            );

            const { status, startTime } = normalizeStatus(rawTimeStatus);

            fixtures.push({
              country: currentCountry,
              league: currentLeague,
              homeTeam,
              awayTeam,
              status,
              startTime,
            });
          }
        }

        return fixtures;
      });

      return {
        data: {
          count: fixtures.length,
          fixtures
        },
        type: 'application/json'
      };
    }
    """

    response = requests.post(
        url,
        headers={"Content-Type": "application/javascript"},
        data=code.encode("utf-8"),
        timeout=360
    )

    print("Status:", response.status_code)

    try:
        parsed = response.json()
        print(json.dumps(parsed, indent=2, ensure_ascii=False))
    except Exception:
        print(response.text)
