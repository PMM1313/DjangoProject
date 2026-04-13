from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP, ROUND_UP

import requests
from django.db import transaction
from datetime import datetime, timedelta, date

from django.db.models import F, Min, Max
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404
from django.utils import timezone

from ..forms import ManualFixtureForm

from .league import LeagueService
from .team import TeamService
from .stats import TrackingValues
from ..models import Team, Fixture, Country, League, Settings, ArchivedFixture, ForRecover, RecoverFixture
from .for_recover import use_plus_for_recovery


class FixtureService:
    API_URL = "https://v3.football.api-sports.io/fixtures"
    API_KEY = "89c35ddda792b7979b1a6298bf817935"
    TIMEZONE = "Europe/Sofia"

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

        response.raise_for_status()
        return response.json()["response"]

    # ---------- CONDITIONS ----------
    def should_import(self, item: dict) -> bool:
        """
        Define your business rules here
        """
        pass

    # ---------- PROCESS AND SAVE BULK ----------
    @transaction.atomic
    def fetch_and_save_fixtures(self, date_from, date_to):
        print(f"Fetch and save method called.")
        start_date = datetime.strptime(date_from, '%Y-%m-%d').date()
        end_date = datetime.strptime(date_to, '%Y-%m-%d').date()
        current_day = start_date

        fixtures_data = []

        while current_day <= end_date:
            # Reusing your existing single-day fetcher
            fixtures = FixtureService.fetch_from_api(current_day.isoformat())
            fixtures_data.extend(fixtures)
            current_day += timedelta(days=1)

        print(f"From: {start_date}, To: {end_date}, Fixtures:{len(fixtures_data)}")

        # 1. Get all tracked IDs once to avoid hitting the DB in every loop iteration
        tracked_team_ids = set(Team.objects.values_list('id', flat=True))
        used_league_ids = set(League.objects.filter(is_used=True).values_list("id", flat=True))
        existing_fixtures = set(Fixture.objects.values_list("home_id", "away_id", "league_id"))

        print(f"Tracked leagues: {used_league_ids}")

        for item in fixtures_data:
            h_id = item["teams"]["home"]["id"]
            a_id = item["teams"]["away"]["id"]
            h_name = item["teams"]["home"]["name"]
            a_name = item["teams"]["away"]["name"]
            league_id = item['league']['id']
            season = item["league"]["season"]

            # 2. Check if at least one team is tracked
            is_h_tracked = h_id in tracked_team_ids
            is_a_tracked = a_id in tracked_team_ids
            is_league_tracked = league_id in used_league_ids

            # 4. Parse Date
            api_date_and_start_time = item["fixture"]["date"]
            # If your model is DateField (not DateTimeField), use .date()
            fixture_date_and_start_time = datetime.fromisoformat(api_date_and_start_time)

            # print(f"step 1")
            if not is_h_tracked and not is_a_tracked and not is_league_tracked:
                # print(f"step 1-2")
                # Skip if neither team is in our "Main" tracked table, and leagues is not used too

                # Delete fixture in db if teams and league are not tracked
                Fixture.objects.filter(home_id=h_id, away_id=a_id, league_id=league_id).delete()
                existing_fixtures.discard((h_id, a_id, league_id))
                # print(f"step 1-3")
                continue

            # print(f"step 1-4")
            league_obj = League.objects.filter(id=item["league"]["id"]).select_related('country').first()

            # in case some of the 2 teams are tracked but league not in DB
            if not league_obj:
                league_obj = LeagueService.update_or_create_league(item["league"])
                print(f"League: {league_obj.name}, Country: {league_obj.country} added to DB")

            country_obj = league_obj.country  # Assuming League model links to Country

            # print(f"step 2")
            # League tracked → auto-import teams for new team that are not in DB, but league is tracked
            if is_league_tracked:
                # Define a list of team data to check
                teams_to_check = [
                    (h_id, h_name, is_h_tracked),
                    (a_id, a_name, is_a_tracked)
                ]

                for team_id, team_name, is_tracked in teams_to_check:
                    if not is_tracked:
                        TeamService.create_team_in_db({
                            "id": team_id,
                            "name": team_name,
                            "league": league_obj,
                            "country": country_obj,
                            "is_active": True
                        })
                        tracked_team_ids.add(team_id)

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
            # 5. Create Fixture using your new schema
            fixture_id = self.generate_fixture_id(fixture_date_and_start_time, h_id, a_id, season,)
            fixture = Fixture.objects.create(
                api_sport_id=item["fixture"]['id'],
                fixture_id=fixture_id,
                home_id=h_id,
                away_id=a_id,
                home_team_name=h_name,
                away_team_name=a_name,
                league=league_obj,
                country=country_obj,
                date=fixture_date_and_start_time,
                home_score=item["score"]["fulltime"]["home"],
                away_score=item["score"]["fulltime"]["away"],
                status=item["fixture"]["status"]["long"],
                season=season,
                # Coefficient, Bets and Plus would be calculated when fixture is played
                # by my odds-service later
            )

            existing_fixtures.add((h_id, a_id, league_id))

            # The corrected, more accurate version:
            league_status = f"League: {league_obj} Used:{is_league_tracked}"
            status = f"{h_name}: {is_h_tracked}, {a_name}: {is_a_tracked}"

            print(f"Created: {h_name} vs {a_name} (Tracked: {status}) ({league_status})")

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
            fixture = get_object_or_404(Fixture, pk=fixture_id)
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
                    bet = FixtureService.calculate_needed_bet(all_bets, coef)
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

                    # save the last played date in the team
                    Team.objects.filter(pk=team.id).update(last_played_date=today)

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
    def calculate_needed_bet(team_all_bets, coef):
        """
        Algebraic Formula: Bet = (AllBets * 1.10) / (Coef - 1.10)
        Calculates the stake needed to cover past losses + 10% markup on total.
        """
        # from .models import Settings  # Local import to avoid circularity

        # 1. Fetch baseline from Settings
        settings = Settings.load()
        min_bet = settings.min_bet

        # The Formula Implementation
        numerator = team_all_bets * Decimal('1.10')
        denominator = coef - Decimal('1.10')

        calculated_bet = numerator / denominator

        # Apply "Floor" (min_bet) and round to 2 decimal places
        final_bet = max(calculated_bet, min_bet)
        return final_bet.quantize(Decimal('0.01'), rounding=ROUND_UP)

    @staticmethod
    def resolve_fixture(fixture_id):
        with transaction.atomic():
            # 1. LOCK the fixture row so no other process can resolve it simultaneously
            fixture = Fixture.objects.select_for_update().get(pk=fixture_id)

            # Identify the teams involved
            team_ids = [fixture.home_id, fixture.away_id]

            if fixture.is_draw:

                # 2. ATOMIC RESET: Update both teams in one hit
                # This is safe because it doesn't rely on Python snapshots
                Team.objects.filter(id__in=team_ids).update(
                    all_bets=0,
                    no_draw=0,
                    extra_bets=0
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
                Team.objects.filter(id__in=team_ids).update(
                    no_draw=Coalesce(F('no_draw'), 0) + 1
                )

                Team.objects.filter(id=fixture.home_id).update(
                    all_bets=Coalesce(F('all_bets'), Decimal('0.00')) + fixture.home_team_bet
                )

                Team.objects.filter(id=fixture.away_id).update(
                    all_bets=Coalesce(F('all_bets'), Decimal('0.00')) + fixture.away_team_bet
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
            country=fixture.country,
            season=fixture.season,
            is_played=fixture.is_played,
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

        # 4. The Fetching Loop
        while current_day <= end_date:
            # isoformat() produces 'YYYY-MM-DD'

            fixtures = FixtureService.fetch_from_api(current_day.isoformat())
            fixtures_data.extend(fixtures)

            current_day += timedelta(days=1)

        # loop finished
        existing_fixtures = set(Fixture.objects.values_list("home_id", "away_id"))
        fixtures_updated = 0

        for item in fixtures_data:
            h_id = item["teams"]["home"]["id"]
            a_id = item["teams"]["away"]["id"]

            if (h_id, a_id) in existing_fixtures:
                Fixture.objects.filter(home_id=h_id, away_id=a_id).update(
                    home_score=item["score"]["fulltime"]["home"],
                    away_score=item["score"]["fulltime"]["away"],
                    status=item["fixture"]["status"]["long"],
                    date=datetime.fromisoformat(item["fixture"]["date"]),
                )

                fixtures_updated += 1
                updated_fixtures.extend(item)
                continue

        print(f"Scores and Statuses updated ! Fixtures updated: {fixtures_updated}")
        print(f"Sync complete. Total days fetched: {(end_date - start_date).days + 1}")
        return updated_fixtures

    @staticmethod
    def generate_fixture_id(date_obj, home_id: int, away_id: int, season: int) -> int:
        # season (4) + month (2) + day (2) + league (4) + home (5) + away (5)
        season_str = str(season).zfill(4)
        month_str = str(date_obj.month).zfill(2)
        day_str = str(date_obj.day).zfill(2)
        # league_str = str(league_id).zfill(4)
        home_str = str(home_id).zfill(5)
        away_str = str(away_id).zfill(5)

        fixture_id_str = f"{season_str}{month_str}{day_str}{home_str}{away_str}"
        return int(fixture_id_str)
