from constance.signals import config_updated
from django.dispatch import receiver
from decimal import Decimal

from core.models import ConstanceAuditLog


@receiver(config_updated)
def handle_constance_setting_change(sender, key, old_value, new_value, **kwargs):
    """
    Тази функция се изпълнява автоматично всеки път,
    когато някоя Constance настройка бъде променена (включително от Admin панела).
    """

    # 1. Проверяваме дали е променена конкретната настройка, която ни интересува
    if key == 'MIN_BET':
        print(f"Настройката MIN_BET е променена от {old_value} на {new_value}!")
        ConstanceAuditLog.objects.create(
            key=key,
            old_value=str(old_value),
            new_value=str(new_value)
        )
        # 👉 ТВОЯТА ДОПЪЛНИТЕЛНА ЛОГИКА ТУК:
        # Например: изчистване на кеш, преизчисляване на данни,
        # извикване на някой твои метод (като Team.redistribute_team_bets_by_no_draw_level) и т.н.

    elif key == 'ALLWAYS_PLUS':
        print(f"Настройката ALLWAYS_PLUS е сменена на: {new_value}")
        if new_value is True:
            # Направи нещо специално, ако стане True
            pass

    elif key == 'ALLWAYS_PLUS_AMOUNT':
        print(f"Настройката ALLWAYS_PLUS_AMOUNT е сменена на: {new_value}")
        if new_value is True:
            # Направи нещо специално, ако стане True
            pass