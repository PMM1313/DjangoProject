# core/tasks.py
from datetime import timedelta
from celery import shared_task
from django.db import transaction
from django.utils import timezone
from .models import Team, TrackingValue


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