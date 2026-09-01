import os
import django

# 1. Set the settings module (Replace 'Server.settings' with your actual settings path)


os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Server.settings')
django.setup()

# 2. Now you can import your models
from core.models import ArchivedFixture

from core.models import ArchivedFixture, League, Fixture
from core.services import fixture, bet
from core.services.team import TeamService
from core.services import browserless


def update_all_fixture_ids():
    # --- Process Active Fixtures ---
    active_fixtures = Fixture.objects.all()
    print(f"Updating {active_fixtures.count()} Active Fixtures...")

    for f in active_fixtures:
        f.fixture_id = fixture.FixtureService.generate_fixture_id(f.date, f.home_id, f.away_id, f.season)
        f.save(update_fields=['fixture_id'])

    # --- Process Archived Fixtures ---
    archived_fixtures = ArchivedFixture.objects.all()
    print(f"Updating {archived_fixtures.count()} Archived Fixtures...")

    for af in archived_fixtures:
        # Check if season exists, otherwise fallback to date.year
        s_val = af.season if af.season else af.date.year

        # !! TRIPLE CHECK THE ORDER HERE !!
        new_id = fixture.FixtureService.generate_fixture_id(af.date, af.home_id, af.away_id, s_val)

        if new_id:
            af.fixture_id = new_id
            af.save(update_fields=['fixture_id'])

    print("--- Update Complete: All IDs synchronized ---")


def change_boolean_type():
    # --- Process Active Fixtures ---
    arch_fixtures = ArchivedFixture.objects.all()
    print(f"Updating {arch_fixtures.count()} Fixtures...")
    count = 0

    for f in arch_fixtures:
        if not f.is_played:
            f.is_played = True
            f.save(update_fields=['is_played'])
            count += 1

    print(f"Updated: {count}")


def test_equalizing_bets():
    result = TeamService.redistribute_team_bets_by_no_draw_level()

    error = False
    for level, (old_total, new_total) in result.items():

        if old_total != new_total:
            error = True

        print(f"Before: {old_total},   After: {new_total}")

    if error:
        print(f'!!!!!!!!!!!!!!! Error in calculations !!!!!!!!!!!!!!!!!!')
    else:
        print(f'No Errors !!!')


def test_simulating_all_bets():
    all_bets = bet.calculate_total_bets_based_on_no_draw_count()
    print(all_bets)


if __name__ == "__main__":
    browserless.scrape_odds_portal()
