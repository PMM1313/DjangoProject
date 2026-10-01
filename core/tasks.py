from celery import shared_task
from .models import Team

@shared_task
def calculate_weekly_bets():
    total_bets = Team.get_total_all_bets()
    # Perform your logic with total_bets here
    return total_bets