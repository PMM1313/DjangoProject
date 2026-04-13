import os

import requests
from django.core.files.base import ContentFile
from urllib.parse import urlparse

from ..models import Team, Country, League
# services/league_service.py
from datetime import date, timedelta


class LeagueService:
    @staticmethod
    def update_or_create_league(league_data: dict) -> League:
        country, _ = Country.objects.get_or_create(
            name=league_data.get("country", "Unknown")
        )

        season_year = league_data.get("season_year", date.today().year)
        season_start = date(season_year, 8, 1)
        season_end = date(season_year + 1, 5, 31)

        league, _ = League.objects.update_or_create(
            id=league_data["id"],
            defaults={
                "name": league_data["name"],
                "country": country,
                "season_year": season_year,
                "season_start": season_start,
                "season_end": season_end,
                "in_season": True,
                "is_used": False,
                "last_updated_date": date.today(),
            }
        )
        return league

    @staticmethod
    def search_external_leagues():

        api_key = "89c35ddda792b7979b1a6298bf817935"

        url = "https://v3.football.api-sports.io/leagues"
        params = {"current": "true", "type": "league"}
        headers = {
            'x-rapidapi-key': api_key,  # Keep this in your settings.py!
            'x-rapidapi-host': 'v3.football.api-sports.io'
        }

        response = requests.get(url, headers=headers, params=params)
        data = response.json()

        # Get IDs of leagues you already have to avoid duplicates
        existing_ids = list(League.objects.values_list('id', flat=True))

        # Filter out leagues you already have
        full_list = data.get('response', [])
        api_data = [item for item in full_list if item['league']['id'] not in existing_ids]

        return api_data

    @staticmethod
    def download_image_to_field(url, field):
        if not url:
            return
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                # Extract filename from URL (e.g., 676.png)
                filename = os.path.basename(urlparse(url).path)
                # Save to the ImageField/FileField
                field.save(filename, ContentFile(response.content), save=False)
        except Exception as e:
            print(f"Failed to download image {url}: {e}")
