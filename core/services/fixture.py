from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP, ROUND_UP
from typing import Optional

import requests
from django.db import transaction, IntegrityError
from datetime import datetime, timedelta, date

from django.db.models import F, Min, Max
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404
from django.utils import timezone

from django.conf import settings

from .league import LeagueService
from .team import TeamService
from .stats import TrackingValues
from .bet import calculate_required_bet
from ..models import Team, Fixture, Country, League, Settings, ArchivedFixture, ForRecover, RecoverFixture
from .for_recover import use_plus_for_recovery


class FixtureService:
    API_URL = getattr(settings, 'API_URL')
    API_KEY = getattr(settings, 'API_KEY')
    TIMEZONE = getattr(settings, 'TIMEZONE')

    # ---------- FETCH ----------

    @staticmethod
    def fetch_from_api(date: str):
        params = {"date": date, "timezone": FixtureService.TIMEZONE}
        headers = {
            'x-apisports-key': FixtureService.API_KEY,
        }

        response = requests.get(FixtureService.API_URL, headers=headers, params=params)
        if response.status_code != 200:
            raise Exception(f"API request failed: {response.status_code} {response.text}")

        data = response.json()

        # Check for API-specific errors (like "Plan restricted")
        if data.get("errors"):
            # The errors field can be a list or a dict, we extract the messages
            error_msgs = data["errors"]
            if isinstance(error_msgs, dict):
                messages = [f"{v}" for v in data["errors"].values()]
                error_msg = " | ".join(messages)
            else:
                error_msg = str(data["errors"])

            # This will be caught by the 'except' block in your view
            raise Exception(f"API Error: {error_msg}")

        return data["response"]

    # ---------- PROCESS AND SAVE BULK ----------
    @transaction.atomic
    def fetch_and_save_fixtures(self, date_from, date_to):
        print(f"Fetch and save method called.")
        start_date = datetime.strptime(date_from, '%Y-%m-%d').date()
        end_date = datetime.strptime(date_to, '%Y-%m-%d').date()
        current_day = start_date

        fixtures_data = []

        while current_day <= end_date:
            # Reusing existing single-day fetcher
            fixtures = FixtureService.fetch_from_api(current_day.isoformat())
            fixtures_data.extend(fixtures)
            current_day += timedelta(days=1)

        print(f"From: {start_date}, To: {end_date}, Fixtures:{len(fixtures_data)}")

        # 1. Get all tracked IDs once to avoid hitting the DB in every loop iteration
        tracked_team_ids = set(Team.objects.filter(is_active=True).values_list('id', flat=True))
        used_league_ids = set(League.objects.filter(is_used=True).values_list("id", flat=True))
        existing_fixtures = set(Fixture.objects.values_list("home_id", "away_id", "league_id"))
        processed_league_logos = set()
        processed_team_logos = set()
        processed_country_flags = set()

        print(f"Tracked leagues: {used_league_ids}")

        for item in fixtures_data:
            h_id = item["teams"]["home"]["id"]
            a_id = item["teams"]["away"]["id"]
            h_name = item["teams"]["home"]["name"]
            a_name = item["teams"]["away"]["name"]
            league_id = item['league']['id']
            season = item["league"]["season"]

            # year_as_int = int(item['fixture']['date'][:4])

            # 2. Check if at least one team is tracked
            is_h_tracked = h_id in tracked_team_ids
            is_a_tracked = a_id in tracked_team_ids
            is_league_tracked = league_id in used_league_ids

            # 4. Parse Date
            # If your model is DateField (not DateTimeField), use .date()
            fixture_date_and_start_time = datetime.fromisoformat(item["fixture"]["date"])

            # print(f"step 1")
            # Skip if neither team is in our "Main" tracked table, and leagues is not used too
            if not is_h_tracked and not is_a_tracked and not is_league_tracked:
                # print(f"step 1-2")

                # 1. Check the local memory set FIRST
                if (h_id, a_id, league_id) in existing_fixtures:
                    # Delete fixture in db if teams and league are not tracked
                    Fixture.objects.filter(home_id=h_id, away_id=a_id, league_id=league_id).delete()
                    existing_fixtures.discard((h_id, a_id, league_id))
                    # print(f"step 1-3")

                continue

            # print(f"step 1-4")
            league_obj = League.objects.filter(id=item["league"]["id"]).select_related('country').first()
            item["league"]["db_object"] = league_obj

            # in case some of the 2 teams are tracked but league not in DB
            if not league_obj:
                league_obj = LeagueService.update_or_create_league(item["league"])
                print(f"League: {league_obj.name}, Country: {league_obj.country} added to DB")
                # check for logo and download it if not

            # check for league logo already processed/downloaded, if not download it
            if league_obj.id not in processed_league_logos:
                if not league_obj.logo:
                    logo_url = item['league'].get('logo')
                    if logo_url:
                        LeagueService.download_image_to_field(logo_url, league_obj.logo)
                        league_obj.save()  # Commits to the instance/staged transaction

                # Mark it as processed so subsequent iterations skip the DB lookups/downloads
                processed_league_logos.add(league_obj.id)

            country_obj = league_obj.country  # Assuming League model links to Country

            # check for country flag if not download it
            # Check if the flag field is empty (no file path in DB)
            if country_obj and country_obj.id not in processed_country_flags:
                if not country_obj.flag:
                    flag_url = item['league'].get('flag')
                    if flag_url:
                        LeagueService.download_image_to_field(flag_url, country_obj.flag)
                        country_obj.save()  # Commit the new flag path to DB

                # Mark it as processed so we skip it for subsequent fixtures of the same country
                processed_country_flags.add(country_obj.id)

            # print(f"step 2")
            # League tracked → auto-import teams for new team that are not in DB, but league is tracked
            # and check if the round is regular season round, so not add teams that play in Promotion
            # for upper league and are actually in lower league, but API provides upper league ID
            if is_league_tracked and item['league']['round'].startswith("Regular Season"):
                # Define a list of team data to check
                teams_to_check = [
                    (h_id, h_name, is_h_tracked),
                    (a_id, a_name, is_a_tracked)
                ]

                for team_id, team_name, is_tracked in teams_to_check:
                    if not is_tracked:  # if team not in DB add it, because league is tracked

                        TeamService.create_team_in_db({
                            "id": team_id,
                            "name": team_name,
                            "league": league_obj,
                            "country": country_obj,
                            "is_active": True
                        })
                        tracked_team_ids.add(team_id)

                # check for team logo

            # print(f"step 3")
            # 3. Check for existing fixture using IDs. can be updated here if new date, match status...
            if (h_id, a_id, league_id) in existing_fixtures:
                Fixture.objects.filter(home_id=h_id, away_id=a_id).update(
                    home_score=item["score"]["fulltime"]["home"],
                    away_score=item["score"]["fulltime"]["away"],
                    status=item["fixture"]["status"]["long"],
                    date=fixture_date_and_start_time,
                )

                continue  # fixture updated, continue to next fixture

            # print(f"step 4")

            # 1. Try to fetch the home and away team objects from your database
            home_team_internal = Team.objects.filter(id=item["teams"]["home"]["id"]).first()
            away_team_internal = Team.objects.filter(id=item["teams"]["away"]["id"]).first()

            # 2. Set names: Use internal name if object exists, else fallback to API name
            h_name = home_team_internal.name if home_team_internal else item["teams"]["home"]["name"]
            a_name = away_team_internal.name if away_team_internal else item["teams"]["away"]["name"]

            item["teams"]["home"]["name"] = h_name
            item["teams"]["away"]["name"] = a_name

            self.create_or_update_fixture_in_db(item, source_name="Api-Sports")

            existing_fixtures.add((h_id, a_id, league_id))

            # check for team logos
            # At the bottom of the loop:
            for side in ['home', 'away']:
                team_id = item['teams'][side]['id']

                if team_id not in processed_team_logos:
                    team_obj = Team.objects.filter(id=team_id).first()
                    if team_obj and not team_obj.logo:
                        team_logo_url = item['teams'][side].get('logo')
                        if team_logo_url:
                            LeagueService.download_image_to_field(team_logo_url, team_obj.logo)
                            team_obj.save()

                    # Mark as processed so we don't query or download for this team again
                    processed_team_logos.add(team_id)

            # The corrected, more accurate version:
            league_status = f"League: {league_obj} Used:{is_league_tracked}"
            status = f"{h_name}: {is_h_tracked}, {a_name}: {is_a_tracked}"

            print(f"Created: {h_name} vs {a_name} (Tracked: {status}) ({league_status})")

    @transaction.atomic
    def create_or_update_fixture_in_db(self, fixture, source_name="Unknown"):

        try:
            fixture["fixture"]["date"] = datetime.fromisoformat(fixture["fixture"]["date"].replace("Z", "+00:00"))
            # league_obj = League.objects.filter(id=fixture["league"]["id"]).select_related('country').first()

            fixture_id = self.generate_fixture_id(
                fixture["fixture"]["date"],
                fixture["teams"]["home"]["id"],
                fixture["teams"]["away"]["id"],
                fixture["fixture"]["date"].year, )

            current_timestamp = timezone.now().isoformat()

            try:
                # 1. Fetch the existing record to inspect it
                fixture_in_db = Fixture.objects.get(fixture_id=fixture_id)
                if not fixture_in_db.sources:
                    fixture_in_db.sources = {}

                fixture_in_db.sources[source_name] = current_timestamp

                # Rule A: If a match is already marked as "Match Finished", don't overwrite
                # its scores or status back to "Not Started"
                # if fixture_in_db.status == "Match Finished" and fixture["fixture"]["status"]["long"] == "Not Started":
                #     # Skip status and score updates, but update other fields if needed
                #     pass
                # else:
                #     fixture_in_db.status = fixture["fixture"]["status"]["long"]
                #     fixture_in_db.home_score = fixture["score"]["fulltime"]["home"]
                #     fixture_in_db.away_score = fixture["score"]["fulltime"]["away"]

                # Rule B: Only update the date if the new date is different (e.g., match was rescheduled)
                if fixture_in_db.date != fixture["fixture"]["date"]:
                    fixture_in_db.date = fixture["fixture"]["date"]

                # # Always update basic info safely
                # fixture_in_db.home_team_name = fixture["teams"]["home"]["name"]
                # fixture_in_db.away_team_name = fixture["teams"]["away"]["name"]

                # Save the modified database object
                fixture_in_db.save()

            except Fixture.DoesNotExist:
                sources = {source_name: current_timestamp}

                fixture_in_db = Fixture.objects.create(
                    api_sport_id=fixture["fixture"]['id'],
                    fixture_id=fixture_id,
                    home_id=fixture["teams"]["home"]["id"],
                    away_id=fixture["teams"]["away"]["id"],
                    home_team_name=fixture["teams"]["home"]["name"],
                    away_team_name=fixture["teams"]["away"]["name"],
                    league=fixture["league"]["db_object"],
                    league_round=fixture['league']['round'],  # db_object
                    country=fixture["league"]["db_object"].country,  # db_object
                    date=fixture["fixture"]["date"],
                    home_score=fixture["score"]["fulltime"]["home"],
                    away_score=fixture["score"]["fulltime"]["away"],
                    status=fixture["fixture"]["status"]["long"],
                    season=fixture["league"]["season"],
                    sources=sources,
                    # Coefficient, Bets and Plus would be calculated when fixture is played
                    # by my odds-service later
                )
                return fixture_in_db

        except KeyError as e:
            # Catches cases where the incoming dictionary format is missing expected keys
            # logger.error(f"Data formatting error. Missing expected key: {e} in fixture payload.")
            raise ValueError(f"Invalid payload structure: missing key {e}") from e

        except ValueError as e:
            # Catches date parsing errors if the date string is malformed
            # logger.error(f"Date parsing error for fixture data: {e}")
            raise

        except IntegrityError as e:
            # Catches database level issues, like violating a Unique Constraint on fixture_id
            # logger.warning(f"Database integrity conflict (likely duplicate fixture_id={fixture_id}): {e}")

            # OPTIONAL: Switch to an update strategy here if it already exists:
            # return self.handle_fixture_update(fixture_id, fixture)
            raise

        except Exception as e:
            # Catch-all for unexpected infrastructure errors (DB down, etc.)
            # logger.critical(f"Unexpected system failure while saving fixture: {e}", exc_info=True)
            raise

    @staticmethod
    def prepare_scraped_data_to_db_fixture_format(raw_fixture):

        league_id = raw_fixture.get('league_id')
        home_id = raw_fixture.get('home_team_id')
        away_id = raw_fixture.get('away_team_id')

        if not all([league_id, home_id, away_id]):
            return

        try:
            league_db_obj = League.objects.select_related('country').get(id=league_id)

            # Build the exact dictionary required by create_or_update_fixture_in_db
            formatted_fixture = {
                "fixture": {
                    "id": None,  # Manual scraping won't have the API-Sport provider ID
                    "date": raw_fixture.get('date'),  # Must be a clean ISO format string
                    "status": {
                        "long": "Not Started"
                    }
                },
                "league": {
                    "db_object": league_db_obj,
                    "round": "Regular Season",
                    "season": league_db_obj.season_year  # FIX: This matches fixture["league"]["season"]
                },
                "teams": {
                    "home": {
                        "id": home_id,
                        "name": raw_fixture.get('home_team_internal_name')
                    },
                    "away": {
                        "id": away_id,
                        "name": raw_fixture.get('away_team_internal_name')
                    }
                }
            }

            return formatted_fixture

        except League.DoesNotExist:
            print(f"❌ League ID {league_id} not found.")
            raise
        except Exception as fixture_error:
            print(f"❌ Error: {str(fixture_error)}")
            raise fixture_error


    @staticmethod
    def get_grouped_fixtures():
        """
        Fetches all fixtures grouped by Country and League,
        ordered by Country, League, and chronological Date/Time.
        """
        fixtures = (
            Fixture.objects
                .select_related('country', 'league')
                # This sorts by Country name, then League name,
                # then by the full timestamp (Year -> Minute)
                .order_by('country__name', 'league__name', 'date')
        )

        # 1. Group using defaultdict
        # Note: Because 'fixtures' is already sorted, the 'list' for each
        # league will maintain that chronological order.
        grouped = defaultdict(lambda: defaultdict(list))
        for fixture in fixtures:
            grouped[fixture.country][fixture.league].append(fixture)

        # 2. Convert to plain dict for Django Template compatibility
        return {
            country: dict(leagues)
            for country, leagues in sorted(grouped.items(), key=lambda x: x[0].name)
        }

    @staticmethod
    def play_match(fixture_id, coefficient):
        with transaction.atomic():
            # 1. Fetch the fixture
            fixture = get_object_or_404(Fixture, fixture_id=fixture_id)
            fixture.coefficient = Decimal(str(coefficient))
            coef = fixture.coefficient
            total_bets = Decimal('0.00')  # sum both teams current bet for DB

            # Find Team objects
            home_team = Team.objects.filter(id=fixture.home_id).first()
            away_team = Team.objects.filter(id=fixture.away_id).first()

            # 2. Process Home and Away Teams
            for side, team in [('home', home_team), ('away', away_team)]:

                bet, profit, plus = Decimal('0.00'), Decimal('0.00'), Decimal('0.00')

                if team:
                    all_bets = Decimal(str(team.all_bets or 0))
                    today = timezone.now().date()

                    # 1. Calculate the rounded-up bet
                    bet = calculate_required_bet(all_bets, coef)
                    total_bets += bet  # sum both team bets

                    # 2. Total money in and out
                    total_return = bet * coef
                    total_cost = all_bets + bet

                    # 3. Calculate EXACT 10% Profit (Target Markup)
                    # We round this to nearest to keep the ledger clean
                    profit = (total_cost * Decimal('0.10')).quantize(Decimal('0.01'), rounding=ROUND_UP)

                    # 4. Calculate PLUS (The actual surplus)
                    # Total Return - (Original Debt + Current Bet + 10% Profit)
                    plus = total_return - (total_cost + profit)
                    plus = max(Decimal('0'), plus).quantize(Decimal('0.01'), rounding=ROUND_UP)

                    # save the last played date in the team and mark as played
                    Team.objects.filter(pk=team.id).update(last_played_date=today, is_played=True)

                # 5. Save to fixture
                setattr(fixture, f"{side}_team_bet", bet)
                setattr(fixture, f"{side}_team_profit", profit)
                setattr(fixture, f"{side}_team_plus", plus)

            # 6. Saving total bets to DB
            TrackingValues.add_entry(total_bets, "BET")

            # 3. Finalize Fixture
            fixture.is_played = True
            fixture.save()

            return fixture

    @staticmethod
    def resolve_fixture(fixture_id):
        with transaction.atomic():

            # 1. LOCK the fixture row so no other process can resolve it simultaneously
            fixture = Fixture.objects.select_for_update().get(fixture_id=fixture_id)

            home_team_id = fixture.home_id
            away_team_id = fixture.away_id

            if fixture.is_draw:

                Team.objects.filter(id__in=[home_team_id, away_team_id]).update(
                    all_bets=Decimal('0.00'),
                    extra_bets=Decimal('0.00'),
                    no_draw=0,
                    is_played=False  # или True, зависи от твоята логика за статус
                )

                # 3. TRACKING: Record the success for the day
                # Sum them here to minimize DB hits
                TrackingValues.add_entry(fixture.home_team_profit + fixture.away_team_profit, "PROFIT")

                # check if use_plus_for_recover is True and use it for recover
                settings = Settings.load()
                use_plus = settings.use_plus_for_recover

                if use_plus and fixture.home_team_plus + fixture.away_team_plus > Decimal('0'):
                    plus_used = use_plus_for_recovery(fixture)

                if fixture.home_team_plus + fixture.away_team_plus > Decimal('0'):
                    TrackingValues.add_entry(fixture.home_team_plus + fixture.away_team_plus, "PLUS_EARNED")

            else:
                # 4. ATOMIC INCREMENT: Add 1 to the current DB value
                # Coalesce ensures that if no_draw is NULL, it starts at 0
                # За домакина
                Team.objects.filter(id=home_team_id).update(
                    all_bets=Coalesce(F('all_bets'), Decimal('0.00')) + fixture.home_team_bet,
                    no_draw=Coalesce(F('no_draw'), 0) + 1,
                    is_played=False
                )

                # За госта
                Team.objects.filter(id=away_team_id).update(
                    all_bets=Coalesce(F('all_bets'), Decimal('0.00')) + fixture.away_team_bet,
                    no_draw=Coalesce(F('no_draw'), 0) + 1,
                    is_played=False
                )

            # 5. ARCHIVE & CLEANUP
            # Create the permanent history record before deleting the active fixture
            FixtureService._create_archive_entry(fixture)
            fixture.delete()

        return True

    @staticmethod
    def resolve_fixture_canceled(fixture_id):
        pass

    @staticmethod
    def _create_archive_entry(fixture):
        """
        Internal helper to map and create the archive record.
        """
        return ArchivedFixture.objects.create(
            fixture_id=fixture.fixture_id,
            api_sport_id=fixture.api_sport_id,
            home_id=fixture.home_id,
            away_id=fixture.away_id,
            home_team_name=fixture.home_team_name,
            away_team_name=fixture.away_team_name,
            home_team_bet=fixture.home_team_bet or 0,
            away_team_bet=fixture.away_team_bet or 0,

            home_team_money_to_recover=fixture.home_team_money_to_recover or 0,
            away_team_money_to_recover=fixture.away_team_money_to_recover or 0,
            home_team_entry_for_recovery_with_bet=fixture.home_team_entry_for_recovery_with_bet or 0,
            away_team_entry_for_recovery_with_bet=fixture.away_team_entry_for_recovery_with_bet or 0,
            home_team_plus_used_for_recovery=fixture.home_team_plus_used_for_recovery or False,
            away_team_plus_used_for_recovery=fixture.away_team_plus_used_for_recovery or False,
            # home_team_plus_used_to_recover=fixture.home_team_plus_used_to_recover,
            # away_team_plus_used_to_recover=fixture.away_team_plus_used_to_recover,
            # home_team_entry_for_recovery_with_plus=fixture.home_team_entry_for_recovery_with_plus,
            # away_team_entry_for_recovery_with_plus=fixture.away_team_entry_for_recovery_with_plus,
            home_team_profit=fixture.home_team_profit or 0,
            away_team_profit=fixture.away_team_profit or 0,
            home_team_plus=fixture.home_team_plus or 0,
            away_team_plus=fixture.away_team_plus or 0,
            coefficient=fixture.coefficient or 0,
            home_score=fixture.home_score,
            away_score=fixture.away_score,
            is_draw=fixture.is_draw,
            date=fixture.date,
            status=fixture.status,
            league_name=fixture.league.name,
            league=fixture.league,
            league_round=fixture.league_round,
            country=fixture.country,
            season=fixture.season,
            is_played=fixture.is_played,
            sources=fixture.sources
        )

    @staticmethod
    def fetch_scores_and_statuses():

        # Get the earliest and latest fixture dates from the DB
        bounds = Fixture.objects.aggregate(
            first_date=Min('date'),
            last_date=Max('date')
        )

        # 2. Extract Date objects with fallback
        # If first_date is 2024-05-01 15:30:00, .date() makes it 2024-05-01
        start_date = bounds['first_date'].date() if bounds['first_date'] else date.today()
        db_end = bounds['last_date'].date() if bounds['last_date'] else date.today()

        # This ensures we don't waste API calls on future dates
        end_date = min(db_end, date.today())

        # 3. Initialize loop variables
        current_day = start_date
        fixtures_data = []
        updated_fixtures = []

        # Tracking for Toast Summary
        success_dates = []
        error_dates = []

        # 4. The Fetching Loop
        while current_day <= end_date:
            day_str = current_day.isoformat()
            try:
                # Attempt to fetch for the specific day
                fixtures = FixtureService.fetch_from_api(day_str)
                fixtures_data.extend(fixtures)
                success_dates.append(day_str)
                print(f"✅ Successfully fetched {len(fixtures)} fixtures for {current_day}")
            except Exception as e:
                error_dates.append(day_str)
                # If API plan limits hit, we just skip this day and continue
                print(f"⚠️ Error !!! .... skipping {current_day}: {str(e)}")

            current_day += timedelta(days=1)

        # loop finished
        existing_fixtures = set(Fixture.objects.values_list("home_id", "away_id"))
        fixtures_updated = 0

        for item in fixtures_data:
            h_id = item["teams"]["home"]["id"]
            a_id = item["teams"]["away"]["id"]

            if (h_id, a_id) in existing_fixtures:
                # 1. Fetch the specific instance
                obj = Fixture.objects.filter(home_id=h_id, away_id=a_id).first()

                if obj:
                    # 2. Update the attributes
                    obj.home_score = item["score"]["fulltime"]["home"]
                    obj.away_score = item["score"]["fulltime"]["away"]
                    obj.status = item["fixture"]["status"]["long"]
                    obj.date = datetime.fromisoformat(item["fixture"]["date"])

                    # 3. Save it (this triggers signals and model logic)
                    obj.save()

                    fixtures_updated += 1
                    updated_fixtures.append(item)  # Use .append() not .extend() for a single item
                    continue

        print(f"Scores and Statuses updated ! Fixtures updated: {fixtures_updated}")
        print(f"Sync complete. Total days fetched: {(end_date - start_date).days + 1}")

        return {
            "updated_count": fixtures_updated,
            "success_dates": success_dates,
            "error_dates": error_dates
        }

    @staticmethod
    def generate_fixture_id(date_obj, home_id: int, away_id: int, year: Optional[int]) -> int:
        # season (4) + month (2) + day (2) + league (4) + home (5) + away (5)

        year_str = '0000'

        if year is None:
            my_date = date.today()

            # Option A: Using .year and str()
            year_str = my_date.strftime('%Y')

        elif year:
            year_str = str(year)

        # Option B: Using .strftime() (Cleanest for formatting)

        month_str = str(date_obj.month).zfill(2)
        day_str = str(date_obj.day).zfill(2)
        # league_str = str(league_id).zfill(4)
        home_str = str(home_id).zfill(5)
        away_str = str(away_id).zfill(5)

        fixture_id_str = f"{year_str}{month_str}{day_str}{home_str}{away_str}"
        return int(fixture_id_str)
