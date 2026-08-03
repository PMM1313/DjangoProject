from decimal import Decimal, ROUND_FLOOR
from django.db import transaction
from django.db.models import Sum, DecimalField
from django.db.models.functions import Coalesce

from ..models import Team, ArchivedFixture, League, Fixture
from django.db.models import Q


class TeamService:

    @staticmethod
    def get_or_create_team(team_data: dict) -> Team:
        """
        Returns a team object, creates if missing.
        Expects team_data to have 'id' and 'name'.
        """
        team, _ = Team.objects.update_or_create(
            id=team_data["id"],  # API ID as PK
            defaults={
                "name": team_data["name"],
                "logo": team_data.get("logo")
            }
        )
        return team

    @staticmethod
    def create_team_in_db(team_data: dict):
        Team.objects.create(
            id=team_data['id'],
            name=team_data['name'],
            league=team_data['league'],
            country=team_data['country'],
            is_active=team_data['is_active']
        )

    @staticmethod
    def gather_streaks():
        data = 1
        return data

    @staticmethod
    def calculate_team_streaks(team_id):
        # Important: ASCENDING order to build the running total up to the present day
        history = ArchivedFixture.objects.filter(
            Q(home_id=team_id) | Q(away_id=team_id)
        ).order_by('date')

        # Current running counters
        s = {
            'odd': 0, 'even': 0, 'over25': 0, 'under25': 0,
            'win': 0, 'draw': 0, 'loss': 0
        }

        for f in history:
            h_score = f.home_score or 0
            a_score = f.away_score or 0
            total = h_score + a_score
            is_home = (f.home_id == team_id)

            # 1. Odd/Even
            if total % 2 != 0:
                s['odd'] += 1
                s['even'] = 0
            else:
                s['even'] += 1
                s['odd'] = 0

            # 2. Over/Under 2.5
            if total > 2.5:
                s['over25'] += 1
                s['under25'] = 0
            else:
                s['under25'] += 1
                s['over25'] = 0

            # 3. Win/Draw/Loss
            if f.is_draw:
                s['draw'] += 1
                s['win'] = 0
                s['loss'] = 0
            elif (is_home and h_score > a_score) or (not is_home and a_score > h_score):
                s['win'] += 1
                s['draw'] = 0
                s['loss'] = 0
            else:
                s['loss'] += 1
                s['win'] = 0
                s['draw'] = 0

        return s

    @staticmethod
    def check_team_league_change(fixture):
        """
            Extracts teams and payload from the Fixture model instance.
            If round starts with 'Regular Season', checks and updates home and away
            teams' league if it differs from the fixture's league.
        """

        # 1. Guard check: Must be "Regular Season" not cup round
        if not fixture['league']['round'].startswith("Regular Season"):
            return

        # 1.1 Guard check: league has to be in DB and league_obj in fixture
        elif not fixture['league']['db_object']:
            return

        h_id = fixture["teams"]["home"]["id"]
        a_id = fixture["teams"]["away"]["id"]

        # Fetch both teams in a single database query
        teams_by_id = Team.objects.in_bulk([h_id, a_id])

        # .get() on a dictionary safely returns None if the key isn't present!
        home_team = teams_by_id.get(h_id)  # Returns Team object or None
        away_team = teams_by_id.get(a_id)  # Returns Team object or None
        league_obj = fixture['league']['db_object']
        teams_to_update = []

        # 2. Iterate through present teams
        for team_obj in [home_team, away_team]:

            if team_obj is None:
                continue

            # Compare existing team league_id with the incoming league model instance ID
            if team_obj.league_id != league_obj.id:
                print(
                    f"🔄 League change for {team_obj.name}: "
                    f"Old League ({team_obj.league_id}) -> "
                    f"New League ({league_obj.id})")

                # Set the new league relationship
                team_obj.league = league_obj
                teams_to_update.append(team_obj)

        # 3. Save only updated teams efficiently
        for team in teams_to_update:
            team.save(update_fields=["league"])

    @staticmethod
    def redistribute_team_bets_by_no_draw_level():
        """
        Преразпределяне на сумите по нива (No draw = 1,2,3,4....
        """
        levels = Team.objects.exclude(no_draw__isnull=True) \
            .values_list('no_draw', flat=True) \
            .distinct() \
            .order_by('no_draw')

        results = {}

        with transaction.atomic():
            for level in levels:
                teams_in_level = Team.objects.filter(no_draw=level, is_played=False).select_for_update()
                count = teams_in_level.count()
                new_total = Decimal('0')

                if count == 0:
                    continue

                # Сумираме
                level_total = teams_in_level.aggregate(
                    total=Coalesce(Sum('all_bets'), Decimal('0'), output_field=DecimalField())
                )['total']

                if level_total == 0:
                    continue

                # Изчисляваме
                base_part = (level_total / count).quantize(Decimal('0.01'), rounding=ROUND_FLOOR)
                remainder_pennies = int((level_total - (base_part * count)) * 100)

                updated_teams = []
                checksum_total = Decimal('0')

                for i, team in enumerate(teams_in_level.order_by('id')):
                    bonus = Decimal('0.01') if i < remainder_pennies else Decimal('0')
                    team.all_bets = base_part + bonus
                    checksum_total += team.all_bets
                    updated_teams.append(team)

                # --- THE RE-CHECK ---
                if checksum_total != level_total:
                    # If the math is wrong, we raise an exception to roll back the WHOLE transaction
                    raise ValueError(f"Math mismatch at level {level}: Expected {level_total}, got {checksum_total}")

                # --- THE SAVE ---
                # Update only the 'all_bets' field for these specific objects
                Team.objects.bulk_update(updated_teams, ['all_bets'])

        return True
