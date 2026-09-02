import os

import requests
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from urllib.parse import urlparse

from django.db import transaction

from ..models import Team, Country, League, TeamLeagueHistory, Fixture
# services/league_service.py
from datetime import date, timedelta
from .country import CountryService


class LeagueService:
    @staticmethod
    def update_or_create_league(league_data: dict) -> League:
        country = CountryService.get_or_create_country(name=league_data.get("country", "Unknown"))

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
    def check_for_league_change(fixture, ht_obj=None, at_obj=None, teams_by_id=None,
                                history_to_create=None, teams_to_update=None):
        """
        Checks a single fixture for league transitions.
        Supports optional accumulator lists for batch database processing.
        """
        league_obj = fixture.league

        if teams_by_id is not None:
            home_team = teams_by_id.get(fixture.home_id)
            away_team = teams_by_id.get(fixture.away_id)
        else:
            home_team = ht_obj
            away_team = at_obj

        for team in [home_team, away_team]:
            if not team:
                continue

            round_str = str(fixture.league_round or '')
            is_different_league = team.league_id != league_obj.id
            is_regular_league = league_obj.regular_league
            is_regular_season_match = round_str.lower().startswith("regular season")

            if is_different_league and is_regular_league and is_regular_season_match:
                old_league_obj = team.league

                if league_obj.id < old_league_obj.id:
                    movement_status = TeamLeagueHistory.StatusChoices.PROMOTION
                else:
                    movement_status = TeamLeagueHistory.StatusChoices.RELEGATION

                # 1. Build history instance in memory
                history_record = TeamLeagueHistory(
                    team=team,
                    old_league=old_league_obj,
                    new_league=league_obj,
                    status=movement_status,
                    showed_ui=0
                )

                # 2. Update team state in memory
                team.league = league_obj
                team.has_league_changes = True

                # 3. Handle batch accumulation or fallback to immediate write
                if history_to_create is not None and teams_to_update is not None:
                    history_to_create.append(history_record)
                    teams_to_update[team.id] = team  # Overwrites if team moved multiple times in process
                else:
                    with transaction.atomic():
                        history_record.save()
                        team.save(update_fields=['league', 'has_league_changes'])

                # Keep local memory lookup fresh
                if teams_by_id is not None:
                    teams_by_id[team.id] = team

    @classmethod
    def process_all_fixtures_league_changes(cls):
        """
        Iterates through all Fixture instances and performs batched bulk writes.
        """
        # In-memory lookups and containers for batch operations
        teams_by_id = {team.id: team for team in Team.objects.select_related('league').all()}

        history_to_create = []
        teams_to_update = {}  # {team_id: team_obj} map prevents duplicate team updates in bulk_update

        # Chunked iterator to keep memory low
        fixtures = Fixture.objects.select_related('league').all().iterator(chunk_size=2000)

        for fixture in fixtures:
            cls.check_for_league_change(
                fixture,
                teams_by_id=teams_by_id,
                history_to_create=history_to_create,
                teams_to_update=teams_to_update
            )

        # Execute bulk database operations inside a single transaction
        if history_to_create or teams_to_update:
            with transaction.atomic():
                if history_to_create:
                    TeamLeagueHistory.objects.bulk_create(history_to_create, batch_size=1000)

                if teams_to_update:
                    Team.objects.bulk_update(
                        list(teams_to_update.values()),
                        fields=['league', 'has_league_changes'],
                        batch_size=1000
                    )

    @staticmethod
    def download_image_to_field(url, field):
        if not url:
            return

        try:
            # Extract filename from URL (e.g., "676.png" or "arg.svg")
            filename = os.path.basename(urlparse(url).path)
            if not filename:
                return

            # Build the relative storage path using the model field's upload_to folder
            upload_to = getattr(field.field, 'upload_to', '')
            # Handle callables if upload_to is a function
            if callable(upload_to):
                upload_to = upload_to(field.instance, filename)
                target_path = upload_to
            else:
                target_path = os.path.join(upload_to, filename)

            # 1. Check if the file already exists on disk/storage
            if default_storage.exists(target_path):
                # Point field directly to the existing file (No re-download, no new file created)
                field.name = target_path
                return

            # 2. File doesn't exist yet: Download and save
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                field.save(filename, ContentFile(response.content), save=False)

        except Exception as e:
            print(f"Failed to download image {url}: {e}")
