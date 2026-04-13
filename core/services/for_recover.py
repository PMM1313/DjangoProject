from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from ..models import Team, Fixture, Country, League, Settings, ArchivedFixture, ForRecover, RecoverFixture
from constance import config


def take_bet_for_recovery():
    bets_to_recover = Decimal('0.00')

    # take the oldest team for recovery
    oldest_entry = ForRecover.objects \
        .select_for_update() \
        .filter(is_recovered=False) \
        .order_by('date_added_to_recover') \
        .first()

    avg_perc_draw = config.AVG_PERC_DRAW / 100
    rounds_for_earn_back = config.ROUNDS_FOR_EARNING_BACK
    all_teams = int((Team.objects.filter(is_active=True)).count())

    all_possible_matches = all_teams * rounds_for_earn_back
    possible_draw_matches = all_possible_matches * avg_perc_draw

    if oldest_entry:
        bets_to_recover = oldest_entry.bets_to_recover

    else:
        return bets_to_recover


def use_plus_for_recovery(fixture):
    with transaction.atomic():
        # Lock rows for safety
        plus_used_amount = Decimal("0")

        entries = ForRecover.objects.select_for_update() \
            .filter(is_recovered=False) \
            .order_by('date_added_to_recover')

        for entry in entries:
            # 1. Try Home Team first
            plus_used, transfer_amount = _process_team_recovery(entry, fixture, "home_team")

            if plus_used:
                plus_used_amount += transfer_amount
                # Create the RecoverFixture entry (the audit trail)
                home_team_obj = Team.objects.filter(id=fixture.home_id).first()
                RecoverFixture.objects.create(
                    for_recover=entry,
                    team=home_team_obj,
                    value=transfer_amount,
                    value_type="plus",
                    fixture_id=fixture.fixture_id
                )

            # 2. Try Away Team second (only if entry still needs money)
            if entry.bets_to_recover > 0:

                plus_used, transfer_amount = _process_team_recovery(entry, fixture, "away_team")

                if plus_used:
                    plus_used_amount += transfer_amount

                    away_team_obj = Team.objects.filter(id=fixture.away_id).first()
                    # Create the RecoverFixture entry (the audit trail)
                    RecoverFixture.objects.create(
                        for_recover=entry,
                        team=away_team_obj,
                        value=transfer_amount,
                        value_type="plus",
                        fixture_id=fixture.fixture_id
                    )


            # 3. Finalize the entry state
            if entry.bets_to_recover <= 0:
                entry.is_recovered = True
                entry.date_recovered = timezone.now()
                entry.save(update_fields=['plus_used_to_recover', 'is_recovered', 'date_recovered'])
            else:
                # Save progress even if not fully finished
                entry.save(update_fields=['plus_used_to_recover'])

            # Optimization: If fixture is totally "empty", stop looping
            if fixture.home_team_plus <= 0 and fixture.away_team_plus <= 0:
                break

        return plus_used_amount


def get_recovery_data():
    queryset = ForRecover.objects.all().order_by('date_added_to_recover')

    # Format the data (Service)
    initial_data = format_recovery_data(queryset)

    return initial_data


def format_recovery_data(queryset):
    return [
        {
            "id": r.id,
            "date_added": r.date_added_to_recover.strftime("%Y-%m-%d %H:%M"),
            "team_name": r.team_name,
            "bets_writen_off": float(r.bets_writen_off),
            "bets_recovered": float(r.bets_recovered),
            "manual_plus": float(r.plus_used_manual),
            "is_recovered": r.is_recovered,
            "bets_to_recover": float(r.bets_to_recover),
            # ... add the rest of your fields here ...
        }
        for r in queryset
    ]


def _process_team_recovery(entry, fixture, team_prefix):
    """
    team_prefix is either 'home_team' or 'away_team'
    """
    # Get the current 'plus' balance dynamically
    plus_used = False
    plus_field = f"{team_prefix}_plus"
    available_plus = getattr(fixture, plus_field)

    # Calculate transfer
    amount_needed = entry.bets_to_recover
    transfer_amount = min(amount_needed, available_plus)

    if transfer_amount > 0:
        # Update entry
        entry.plus_used_to_recover += transfer_amount

        # Update fixture plus balance
        new_plus_balance = available_plus - transfer_amount
        setattr(fixture, plus_field, new_plus_balance)

        boolean_field = f"{team_prefix}_plus_used_for_recovery"
        setattr(fixture, boolean_field, True)
        plus_used = True
        # Update fixture tracking fields
        # setattr(fixture, f"{team_prefix}_entry_for_recovery_with_plus", entry.id)
        # setattr(fixture, f"{team_prefix}_plus_used_to_recover", transfer_amount)

        # Save the fixture immediately to keep balances accurate
        fixture.save(update_fields=[
            plus_field,
            boolean_field,
            # f"{team_prefix}_entry_for_recovery_with_plus",
            # f"{team_prefix}_plus_used_to_recover"
        ])

    return plus_used, transfer_amount
