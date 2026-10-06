from datetime import date, datetime, timedelta, time
from django.db.models import F, Sum, DecimalField, Q, Count
from django.db.models.functions import TruncWeek, TruncMonth, TruncYear, Coalesce
from ..models import TrackingValue, Fixture, Team, ArchivedFixture
from django.utils import timezone

from decimal import Decimal
from django.db import transaction


def format_week_range_date(start_of_week, end_of_week):
    """
    Consistently formats Monday-Sunday date ranges as:
    DD.MM - DD.MM.YY (e.g., '17.08 - 23.08.26' or '31.08 - 06.09.26')
    """
    start_str = start_of_week.strftime('%d.%m')
    end_str = end_of_week.strftime('%d.%m.%y')
    return f"{start_str} - {end_str}"

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
    def get_stats_table_data(weeks_count=8):
        today = timezone.localdate()
        current_monday = today - timedelta(days=today.weekday())

        # 1. Build week metadata map
        weeks_map = {}
        for i in range(weeks_count):
            start = current_monday - timedelta(weeks=i)
            end = start + timedelta(days=6)
            weeks_map[start] = {
                'start': start,
                'end': end,
                'is_current_week': (i == 0),
                'formatted_date': format_week_range_date(start, end),
            }

        oldest_monday = current_monday - timedelta(weeks=weeks_count - 1)
        newest_sunday = current_monday + timedelta(days=6)

        # Query 1: TrackingValues bulk stats
        weekly_stats_qs = (
            TrackingValue.objects.filter(
                date__range=[oldest_monday, newest_sunday]
            )
            .annotate(week=TruncWeek('date'))
            .values('week')
            .annotate(
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
        )

        aggregated_by_week = {
            (item['week'].date() if hasattr(item['week'], 'date') else item['week']): item
            for item in weekly_stats_qs
        }

        # Queries 2 & 3: Bulk fixture draw stats
        bulk_draw_stats = TrackingValues.get_bulk_weekly_draw_stats(oldest_monday, newest_sunday)

        current_total_all_bets = Team.get_total_all_bets()
        results = []

        # 2. Assemble in chronological order (oldest -> newest)
        for start_date, week_info in reversed(list(weeks_map.items())):
            stats = aggregated_by_week.get(start_date, {})
            draw_info = bulk_draw_stats.get(start_date, {'played': 0, 'draws': 0})

            fixtures_played = draw_info['played']
            draws = draw_info['draws']
            draw_percent = (
                round((draws / fixtures_played) * 100, 2)
                if fixtures_played > 0
                else Decimal('0.00')
            )

            bets_val = stats.get('bets', Decimal('0.00'))
            profit_val = stats.get('profit', Decimal('0.00'))

            profit_percent = (
                round((profit_val / bets_val) * 100, 2)
                if bets_val > 0
                else Decimal('0.00')
            )

            all_bets_start = stats.get('all_bets_start')
            all_bets_end = stats.get('all_bets_end')

            results.append(
                {
                    'date': week_info['formatted_date'],
                    'all_bets_start_of_week': (
                        all_bets_start if all_bets_start is not None else 'Not set'
                    ),
                    'all_bets_current': (
                        current_total_all_bets
                        if week_info['is_current_week']
                        else 'N/A'
                    ),
                    'all_bets_end_of_week': (
                        all_bets_end
                        if all_bets_end is not None
                        else (
                            'No snapshot yet'
                            if week_info['is_current_week']
                            else 'Not set'
                        )
                    ),
                    'fixtures_played': fixtures_played,
                    'draw': draws,
                    'draw_percent': f"{draw_percent}%",
                    'bets': bets_val,
                    'profit': profit_val,
                    'profit_percent': f"{profit_percent}%",
                    'plus_earned': stats.get('plus_earned', Decimal('0.00')),
                    'plus_for_recover': 'Not calculated',
                }
            )

        return results

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
    def get_bulk_weekly_draw_stats(start_date, end_date):
        """Calculates weekly draw stats for a full date range across active and archived

        fixtures in just 2 SQL queries.
        """
        tz = timezone.get_current_timezone()
        start_dt = timezone.make_aware(datetime.combine(start_date, time.min), tz)
        end_dt = timezone.make_aware(datetime.combine(end_date, time.max), tz)

        # 1. Query Active Fixtures grouped by week
        active_stats = (
            Fixture.objects.filter(
                date__range=(start_dt, end_dt),
                is_played=True
            )
            .annotate(week=TruncWeek('date'))
            .values('week')
            .annotate(
                played_count=Count('id'),
                draws_count=Count('id', filter=Q(home_score__isnull=False, home_score=F('away_score')))
            )
        )

        # 2. Query Archived Fixtures grouped by week
        archived_stats = (
            ArchivedFixture.objects.filter(
                date__range=(start_dt, end_dt),
                is_played=True
            )
            .annotate(week=TruncWeek('date'))
            .values('week')
            .annotate(
                played_count=Count('id'),
                draws_count=Count('id', filter=Q(is_draw=True))
            )
        )

        # 3. Consolidate into a dictionary keyed by week (date)
        stats_by_week = {}

        def merge_stats(queryset):
            for item in queryset:
                # Standardize week key to a date object (Monday)
                week_key = item['week'].date() if hasattr(item['week'], 'date') else item['week']
                if week_key not in stats_by_week:
                    stats_by_week[week_key] = {'played': 0, 'draws': 0}

                stats_by_week[week_key]['played'] += item['played_count']
                stats_by_week[week_key]['draws'] += item['draws_count']

        merge_stats(active_stats)
        merge_stats(archived_stats)

        return stats_by_week

