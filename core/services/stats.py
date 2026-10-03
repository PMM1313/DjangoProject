from datetime import date, datetime, timedelta, time
from django.db.models import F, Sum, DecimalField, Q
from django.db.models.functions import TruncWeek, TruncMonth, TruncYear, Coalesce
from ..models import TrackingValue, Fixture, Team, ArchivedFixture
from django.utils import timezone

from decimal import Decimal
from django.db import transaction




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
        # 1. Always use Django local date for timezone safety (Sofia time)
        today = timezone.localdate()

        start_of_week = today - timedelta(days=today.weekday())  # Monday
        end_of_week = start_of_week + timedelta(days=6)  # Sunday

        # 2. Handle date formatting when week spans two months
        if start_of_week.month == end_of_week.month:
            date_formatted = f"{start_of_week.strftime('%d')} - {end_of_week.strftime('%d %m.%y')}"
        else:
            date_formatted = f"{start_of_week.strftime('%d.%m')} - {end_of_week.strftime('%d.%m.%y')}"

        # Calculate fixtures played across both active and archived tables
        fixtures_stats = TrackingValues.get_weekly_draw_stats(
            start_of_week, end_of_week
        )

        # 3. Single-query aggregation for all TrackingValue categories in this week
        weekly_totals = TrackingValue.objects.filter(
            date__range=[start_of_week, end_of_week]
        ).aggregate(
            bets=Coalesce(
                Sum('amount', filter=Q(category='BET')),
                Decimal('0.00'),
                output_field=DecimalField(),
            ),
            profit=Coalesce(
                Sum('amount', filter=Q(category='PROFIT')),
                Decimal('0.00'),
                output_field=DecimalField(),
            ),
            plus_earned=Coalesce(
                Sum('amount', filter=Q(category='PLUS_EARNED')),
                Decimal('0.00'),
                output_field=DecimalField(),
            ),
            plus_used=Coalesce(
                Sum('amount', filter=Q(category='PLUS_USED')),
                Decimal('0.00'),
                output_field=DecimalField(),
            ),
            all_bets_start=Coalesce(
                Sum('amount', filter=Q(category='ALL_BETS_SNAPSHOT_START')),
                None,
                output_field=DecimalField(),
            ),
            all_bets_end=Coalesce(
                Sum('amount', filter=Q(category='ALL_BETS_SNAPSHOT_END')),
                None,
                output_field=DecimalField(),
            ),
        )

        # 4. Fetch live 'all_bets_current' from Team model
        current_total_all_bets = Team.get_total_all_bets()

        # 5. Calculate derived percentages safely (avoid ZeroDivisionError)
        bets_val = weekly_totals['bets']
        profit_val = weekly_totals['profit']

        profit_percent = (
            round((profit_val / bets_val) * 100, 2)
            if bets_val > 0
            else Decimal('0.00')
        )

        return [
            {
                'date': date_formatted,
                'all_bets_start_of_week': (
                    weekly_totals['all_bets_start']
                    if weekly_totals['all_bets_start'] is not None
                    else 'Not set'
                ),
                'all_bets_current': current_total_all_bets,
                'all_bets_end_of_week': (
                    weekly_totals['all_bets_end']
                    if weekly_totals['all_bets_end'] is not None
                    else 'No snapshot yet'
                ),
                'fixtures_played': fixtures_stats['fixtures_played'],
                'draw': fixtures_stats['draws'],  # <--- Draw count
                'draw_percent': fixtures_stats['draw_percent'],  # <--- Draw %
                'bets': bets_val,
                'profit': profit_val,
                'profit_percent': f"{profit_percent}%",
                'plus_earned': weekly_totals['plus_earned'],
                'plus_for_recover': 'Not calculated',
            }
        ]

    @staticmethod
    def apply_snapshot_delta(fixture : Fixture, delta: Decimal):
        """Applies a delta change to snapshots.

        - Leaves event week's START snapshot untouched.
        - Updates event week's END snapshot.
        - Updates all subsequent week START & END snapshots.
        """
        if not delta or delta == Decimal('0'):
            return 0

        today = timezone.localdate()
        current_monday = today - timedelta(days=today.weekday())
        event_date = timezone.localtime(fixture.date).date()

        # Skip if the event occurred in the current active week
        if event_date >= current_monday:
            return 0

        # Calculate week boundaries
        event_monday = event_date - timedelta(days=event_date.weekday())
        first_affected_sunday = event_monday + timedelta(days=6)
        following_monday = first_affected_sunday + timedelta(days=1)

        with transaction.atomic():
            # 1. Update END snapshots starting from event week's Sunday
            updated_ends = TrackingValue.objects.filter(
                date__gte=first_affected_sunday,
                category='ALL_BETS_SNAPSHOT_END',
            ).update(amount=F('amount') + delta)

            # 2. Update START snapshots starting ONLY from next week's Monday
            updated_starts = TrackingValue.objects.filter(
                date__gte=following_monday,
                category='ALL_BETS_SNAPSHOT_START',
            ).update(amount=F('amount') + delta)

        return f"Updated delta for {updated_ends} and {updated_starts}"

    @staticmethod
    def get_weekly_draw_stats(start_of_week, end_of_week):
        """Calculates total played fixtures, draw count, and draw percentage across

        both Fixture and ArchivedFixture models for the week.
        """
        tz = timezone.get_current_timezone()
        start_dt = timezone.make_aware(
            datetime.combine(start_of_week, time.min), tz
        )
        end_dt = timezone.make_aware(datetime.combine(end_of_week, time.max), tz)

        # 1. Count draws and total played in active Fixtures
        active_played = Fixture.objects.filter(
            date__range=(start_dt, end_dt), is_played=True
        )
        active_played_count = active_played.count()
        active_draws_count = active_played.filter(
            home_score__isnull=False, home_score=F('away_score')
        ).count()

        # 2. Count draws and total played in ArchivedFixtures
        archived_played = ArchivedFixture.objects.filter(
            date__range=(start_dt, end_dt), is_played=True
        )
        archived_played_count = archived_played.count()
        archived_draws_count = archived_played.filter(is_draw=True).count()

        # 3. Combine totals
        total_fixtures_played = active_played_count + archived_played_count
        total_draws = active_draws_count + archived_draws_count

        # 4. Calculate percentage safely
        if total_fixtures_played > 0:
            draw_percent = round((total_draws / total_fixtures_played) * 100, 2)
        else:
            draw_percent = Decimal('0.00')

        return {
            'fixtures_played': total_fixtures_played,
            'draws': total_draws,
            'draw_percent': f"{draw_percent}%",
        }

