from decimal import Decimal
from django.db.models import Sum
from ..models import Team, Settings
from decimal import Decimal, ROUND_HALF_UP, ROUND_UP


def calculate_total_bets_based_on_no_draw_count(no_draw_count: int):
    settings = Settings.load()
    min_bet = settings.min_bet
    coef = Decimal("3.60")
    all_bets = Decimal("0.00")

    for play in range(1, no_draw_count + 1):
        bet = calculate_required_bet(all_bets, coef)
        all_bets += bet

    return all_bets, min_bet, coef


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
