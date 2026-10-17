# core/tasks.py
import logging
from datetime import timedelta
from decimal import Decimal

from celery import shared_task
from django.db import transaction
from django.utils import timezone
from .models import Team, TrackingValue
from django.db.models import Count, Sum, Max

logger = logging.getLogger(__name__)

@shared_task
def calculate_weekly_bets():
    # Base calculation on today's local date
    current_date = timezone.localdate()

    # Find the Monday of the current week (weekday() returns 0 for Monday)
    this_monday = current_date - timedelta(days=current_date.weekday())
    last_sunday = this_monday - timedelta(days=1)

    # Sum up all_bets across teams
    total_bets = Team.get_total_all_bets()

    with transaction.atomic():
        # 1. End snapshot recorded on the preceding Sunday
        TrackingValue.objects.update_or_create(
            date=last_sunday,
            category='ALL_BETS_SNAPSHOT_END',
            defaults={'amount': total_bets},
        )

        # 2. Start snapshot recorded on this Monday
        TrackingValue.objects.update_or_create(
            date=this_monday,
            category='ALL_BETS_SNAPSHOT_START',
            defaults={'amount': total_bets},
        )

    return f"Snapshots updated — Sunday ({last_sunday}) & Monday ({this_monday}): {total_bets}"

@shared_task(name="core.tasks.calculate_no_draw_brackets")
def calculate_no_draw_brackets():
    """
    Calculate the number of teams and total all_bets
    for each no_draw bracket, from 0 to the maximum.
    """
    # Base calculation on today's local date
    current_date = timezone.localdate()

    # Find the Monday of the current week (weekday() returns 0 for Monday)
    this_monday = current_date - timedelta(days=current_date.weekday())

    grouped_results = (
        Team.objects
        .values("no_draw")
        .annotate(
            team_count=Count("pk"),
            total_bets=Sum("all_bets"),
        ).order_by("no_draw")
    )

    results = {
        row["no_draw"]: {
            "team_count": row["team_count"],
            "total_bets": str(row["total_bets"] or Decimal("0.00")),
        }
        for row in grouped_results
    }

    ############ write the result in TrackingValues ##################
    # Use the current local date as the snapshot date.

    with transaction.atomic():
        for bracket, data in results.items():
            # Save the number of teams.
            TrackingValue.objects.update_or_create(
                date=this_monday,
                category=f"ND_COUNT_{bracket}",
                defaults={
                    "amount": data["team_count"],
                },
            )

            # Save the total bets for these teams.
            TrackingValue.objects.update_or_create(
                date=this_monday,
                category=f"ND_BETS_{bracket}",
                defaults={
                    "amount": data["total_bets"],
                },
            )
    ############ END OF write the result in TrackingValues ##################
    return results