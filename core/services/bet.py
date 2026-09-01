from decimal import Decimal
from django.db.models import Sum
from ..models import Team, Settings
from decimal import Decimal, ROUND_HALF_UP, ROUND_UP
from django.db.models import Max


def calculate_total_bets_based_on_no_draw_count():
    """

    Calculates theoretical cumulative bets for each ND (no draw) step from 0
    up to the highest ND value among all active teams.

    :return: dict {nd (int): all_bets (Decimal)}

    """
    # Fetch active teams and get the highest 'no_draw' count
    active_teams = Team.objects.filter(is_active=True)

    # Get maximum ND value; default to 0 if no active teams or all NDs are null
    max_nd = active_teams.aggregate(max_nd=Max('no_draw'))['max_nd'] or 0

    results = {
        0: Decimal("0.00")
    }
    all_bets = Decimal("0.00")

    settings = Settings.load()

    avg_coefficient = settings.avg_coefficient

    # Range starts at 0 up to max_nd inclusive
    for play in range(1, max_nd + 1):
        bet = calculate_required_bet(all_bets, avg_coefficient)
        all_bets += bet
        results[play] = all_bets

    return results


def calculate_required_bet(team_all_bets, coef):
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
