from decimal import Decimal
from django.db.models import Sum
from ..models import Team


def calculate_required_bet(team_id, multiplier):
    # 1. Constants
    MIN_BET = Decimal('0.28')
    PROFIT_MARGIN = Decimal('1.1')  # The 10% buffer

    # 2. Get past bets from Postgres
    past_bets_data = Team.objects.filter(team_id=team_id).aggregate(Sum('amount'))
    past_bets = past_bets_data['amount__sum'] or Decimal('0.00')

    mult = Decimal(str(multiplier))

    # 3. Guard against impossible math
    if mult <= PROFIT_MARGIN:
        raise ValueError(f"Multiplier must be greater than {PROFIT_MARGIN}")

    # 4. Calculate the required bet using our formula
    # bet = (past * 1.1) / (mult - 1.1)
    calculated_bet = (past_bets * PROFIT_MARGIN) / (mult - PROFIT_MARGIN)

    # 5. Logic: Use the higher of the two (Calculated vs Minimum)
    final_bet = max(calculated_bet, MIN_BET)

    # 6. Format to 2 decimal places
    return final_bet.quantize(Decimal('0.01'))


