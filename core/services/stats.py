from datetime import date, datetime, timedelta
from django.db.models import F, Sum
from django.db.models.functions import TruncWeek, TruncMonth, TruncYear
from ..models import TrackingValue


class TrackingValues:

    @staticmethod
    def add_entry(amount, category, entry_date=None):
        """
        Updates the daily total for a category if it exists,
        otherwise creates a new one.
        """
        # Default to today if no specific date is provided
        if entry_date is None:
            entry_date = date.today()
        elif isinstance(entry_date, datetime):
            # Convert datetime to date automatically
            entry_date = entry_date.date()

        # Ensure category is valid based on your model choices
        valid_categories = [c[0] for c in TrackingValue.TYPE_CHOICES]
        if category not in valid_categories:
            raise ValueError(f"Invalid category. Choose from: {valid_categories}")

        # get_or_create finds the specific row for today and that category
        obj, created = TrackingValue.objects.get_or_create(
            date=entry_date,
            category=category
        )

        # Using F() expression to add the amount directly in PostgreSQL
        # This is safer than doing obj.amount += amount in Python
        TrackingValue.objects.filter(pk=obj.pk).update(amount=F('amount') + amount)

    @staticmethod
    def get_report(timeframe='month', category=None):
        """
        Exports data grouped by the chosen timeframe.
        :param timeframe: 'week', 'month', or 'year'
        :param category: Optional filter for 'PROFIT', 'BET', or 'PLUS_EARNED', 'PLUS_USED'
        """
        # Select the correct PostgreSQL truncation function
        trunc_map = {
            'week': TruncWeek('date'),
            'month': TruncMonth('date'),
            'year': TruncYear('date')
        }

        trunc_func = trunc_map.get(timeframe.lower(), TruncMonth('date'))

        queryset = TrackingValue.objects.all()

        # Filter by category if one is provided
        if category:
            queryset = queryset.filter(category=category)

        return (
            queryset
                .annotate(period=trunc_func)
                .values('period', 'category')
                .annotate(total_amount=Sum('amount'))
                .order_by('-period', 'category')
        )

    @staticmethod
    def get_stats_table_data():
        today = date.today()

        # Calculate Monday (start of week) and Sunday (end of week)
        start_of_week = today - timedelta(days=today.weekday())
        end_of_week = start_of_week + timedelta(days=6)

        # Format date string: "21 - 27 09.26"
        date_formatted = f"{start_of_week.strftime('%d')} - {end_of_week.strftime('%d')} {start_of_week.strftime('%m.%y')}"

        # Fetch records within the current week range
        weekly_records = TrackingValue.objects.filter(
            date__range=[start_of_week, end_of_week]
        )

        # Aggregate sums for BET and PROFIT (default to 0 if None)
        total_bets = weekly_records.filter(category='BET').aggregate(Sum('amount'))['amount__sum'] or 0
        total_profit = weekly_records.filter(category='PROFIT').aggregate(Sum('amount'))['amount__sum'] or 0

        # Return list of dictionaries to easily iterate in template
        return [
            {
                'date': date_formatted,
                'bets_in_progression': 'Not set',
                'fixtures_played': 'Not set',
                'draw': 'Not set',
                'draw_percent': 'Not set',
                'bets': total_bets,
                'profit': total_profit,
                'profit_percent': 'Not set',
                'plus_earned': 'Not set',
                'plus_for_recover': 'Not set',
            }
        ]
