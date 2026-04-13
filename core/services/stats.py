from datetime import date
from django.db.models import F, Sum
from django.db.models.functions import TruncWeek, TruncMonth, TruncYear
from ..models import TrackingValue


class TrackingValues:

    @staticmethod
    def add_entry(amount, category):
        """
        Updates the daily total for a category if it exists,
        otherwise creates a new one.
        """
        # Ensure category is valid based on your model choices
        valid_categories = [c[0] for c in TrackingValue.TYPE_CHOICES]
        if category not in valid_categories:
            raise ValueError(f"Invalid category. Choose from: {valid_categories}")

        # get_or_create finds the specific row for today and that category
        obj, created = TrackingValue.objects.get_or_create(
            date=date.today(),
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
