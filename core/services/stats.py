from datetime import date, datetime, timedelta, time
from django.db.models import F, Sum, DecimalField, Q, Count, Avg
from django.db.models.functions import TruncWeek, TruncMonth, TruncYear, Coalesce
from ..models import TrackingValue, Fixture, Team, ArchivedFixture, RecoverFixture
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
        if entry_date is None:
            entry_date = timezone.localdate()
        elif isinstance(entry_date, datetime):
            # Convert UTC datetime to local time (Europe/Sofia) before extracting .date()
            entry_date = timezone.localtime(entry_date).date()

        obj, created = TrackingValue.objects.get_or_create(
            date=entry_date,
            category=category
        )

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

        # Query 1: TrackingValue bulk stats from Trackingvalue table
        # Fetches BET, PROFIT, PLUS_EARNED, PLUS_USED, ALL_BETS_SNAPSHOT_START, ALL_BETS_SNAPSHOT_END
        weekly_stats_qs = TrackingValues.get_bulk_from_trackingvalues_table(oldest_monday, newest_sunday)

        # Queries 2 & 3: Bulk fixture draw stats from Fixture and ArhivedFixture tables
        bulk_draw_stats = TrackingValues.get_bulk_weekly_draw_stats(oldest_monday, newest_sunday)

        # get avg coefs for the weeks from Fixture and ArhivedFixture tables
        bulk_avg_coefs = TrackingValues.get_bulk_weekly_avg_coefficient(oldest_monday, newest_sunday)

        # get plus earned from the fixture itself. doesn't account used plus
        bulk_plus_used = TrackingValues.get_bulk_weekly_plus_earned(oldest_monday, newest_sunday)

        # get guaranteed plus winnings from Fixture and ArhivedFixture
        bulk_gp_plus = TrackingValues.get_bulk_weekly_gp_plus_draws(oldest_monday, newest_sunday)

        # get all normal past bets for all Teams from Team table
        current_total_all_bets = Team.get_total_all_bets()

        # get plus used for the current week from recoverfixture table
        bulk_plus_used = TrackingValues.get_bulk_plus_used(oldest_monday, newest_sunday)

        # result returned used for context for the table in the UI
        results = []

        # 2. Assemble in chronological order (oldest -> newest)
        for start_date, week_info in reversed(weeks_map.items()):

            stats = weekly_stats_qs.get(start_date, {})

            draw_info = bulk_draw_stats.get(start_date, {'played': 0, 'draws': 0})

            # get avg coef for the week with the start day key
            avg_coefficient = bulk_avg_coefs.get(start_date, Decimal('0.00'))

            # plus earned for the week (without plus used into account)
            plus_earned = bulk_plus_used.get(start_date, Decimal('0.00'))

            # guaranteed plus winnings for the week
            total_gp_plus = bulk_gp_plus.get(start_date, Decimal('0.000'))

            # plus used for the week including manual plus taken from each
            # recoverfixture entry
            plus_used = bulk_plus_used.get(start_date, Decimal('0.00'))

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
                    'plus_earned': plus_earned,
                    'plus_for_recover': plus_used,
                    'avg_coefficient': avg_coefficient,
                    'total_gp_plus': total_gp_plus,
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

    @staticmethod
    def update_tracking_value(snapshot_date, category, delta):
        """Create the TrackingValue if missing, then adjust its amount."""
        tracking_value, created = TrackingValue.objects.get_or_create(
            date=snapshot_date,
            category=category,
            defaults={"amount": 0},
        )

        if created:
            # The new row starts at zero, so apply the delta directly.
            tracking_value.amount = delta
            tracking_value.save(update_fields=["amount"])
        else:
            TrackingValue.objects.filter(pk=tracking_value.pk).update(
                amount=F("amount") + delta
            )

    @staticmethod
    @transaction.atomic
    def update_no_draw_brackets(teams_with_bets, is_draw, snapshot_date):

        for team, current_bet in teams_with_bets:

            if team is None:
                continue

            bracket = team.no_draw

            # Every result removes this team from its previous bracket.
            TrackingValues.update_tracking_value(
                snapshot_date,
                f"ND_COUNT_{bracket}",
                -1 if bracket > 0 else 0, # if its second draw in a raw, snapshot already got it at ND 0
            )

            if is_draw:
                # # A draw resets the team's no-draw streak to zero.
                # TrackingValues.update_tracking_value(
                #     snapshot_date,
                #     f"ND_COUNT_0",
                #     1 if bracket > 0 else 0, # if its second draw in a raw, snapshot already got it at ND 0,
                # )

                # Remove this team's accumulated bets from its old bracket.
                TrackingValues.update_tracking_value(
                    snapshot_date,
                    f"ND_BETS_{bracket}",
                    -team.all_bets,
                )

            else:
                # A non-draw moves the team to the next bracket.
                TrackingValues.update_tracking_value(
                    snapshot_date,
                    f"ND_COUNT_{bracket + 1}",
                    1,
                )

                # Add the all_bets and current bet to the next bracket.
                TrackingValues.update_tracking_value(
                    snapshot_date,
                    f"ND_BETS_{bracket + 1}",
                    team.all_bets + current_bet,
                )

                # remove all bets from previous bracket
                TrackingValues.update_tracking_value(
                    snapshot_date,
                    f"ND_BETS_{bracket}",
                    -team.all_bets,
                )

    @staticmethod
    def get_bulk_weekly_avg_coefficient(oldest_monday, newest_sunday):
        """
        Calculates the average coefficient for played fixtures across both
        Fixture and ArchivedFixture models, grouped by week within the date range.
        Ensures all weeks in the range are represented.
        """
        date_range = [oldest_monday, newest_sunday + timedelta(days=1)]

        def get_week_key(item):
            w = item['week']
            return w.date() if hasattr(w, 'date') else w

        combined_stats = {}

        # 1. Aggregate from active Fixtures
        fixture_stats = (
            Fixture.objects.filter(
                date__range=date_range,
                is_played=True,
                coefficient__isnull=False
            )
            .annotate(week=TruncWeek('date'))
            .values('week')
            .annotate(
                total_coef=Sum('coefficient'),
                count_coef=Count('coefficient')
            )
        )
        for item in fixture_stats:
            week_key = get_week_key(item)
            combined_stats[week_key] = {
                'total': item['total_coef'] or Decimal('0.00'),
                'count': item['count_coef'] or 0
            }

        # 2. Aggregate from ArchivedFixtures and merge
        archived_stats = (
            ArchivedFixture.objects.filter(
                date__range=date_range,
                is_played=True,
                coefficient__isnull=False
            )
            .annotate(week=TruncWeek('date'))
            .values('week')
            .annotate(
                total_coef=Sum('coefficient'),
                count_coef=Count('coefficient')
            )
        )
        for item in archived_stats:
            week_key = get_week_key(item)
            if week_key in combined_stats:
                combined_stats[week_key]['total'] += item['total_coef'] or Decimal('0.00')
                combined_stats[week_key]['count'] += item['count_coef'] or 0
            else:
                combined_stats[week_key] = {
                    'total': item['total_coef'] or Decimal('0.00'),
                    'count': item['count_coef'] or 0
                }

        # 3. Build a complete dictionary for every week from oldest_monday to newest_sunday
        result = {}
        curr = oldest_monday
        while curr <= newest_sunday:
            data = combined_stats.get(curr)
            if data and data['count'] > 0:
                avg_val = data['total'] / Decimal(data['count'])
                result[curr] = round(avg_val, 2)
            else:
                result[curr] = Decimal('0.00')
            curr += timedelta(weeks=1)

        return result

    @staticmethod
    def get_bulk_from_trackingvalues_table(oldest_monday, newest_sunday):
        """
        Returns a dictionary mapping each week's start date to its aggregated stats:
        {
            datetime.date(2026, 10, 19): {
                'week': datetime.date(2026, 10, 19),
                'bets': Decimal('150.00'),
                'profit': Decimal('25.50'),
                'plus_earned': Decimal('5.00'),
                # ... other fields ...
            },
            datetime.date(2026, 10, 12): {
                'week': datetime.date(2026, 10, 12),
                'bets': Decimal('200.00'),
                'profit': Decimal('-10.00'),
                # ...
            }
        }
        """
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

        return aggregated_by_week

    @staticmethod
    def get_bulk_weekly_gp_plus_draws(oldest_monday, newest_sunday):
        """
        Calculates the sum of home_team_gp_plus + away_team_gp_plus for
        fixtures where status='Match Finished', is_played=True, and is_draw=True,
        across both models, grouped by week.
        """
        date_range = [oldest_monday, newest_sunday + timedelta(days=1)]

        def get_week_key(item):
            w = item['week']
            return w.date() if hasattr(w, 'date') else w

        combined_stats = {}

        # Helper to aggregate GP plus data
        def process_gp(qs_class):
            stats = (
                qs_class.objects.filter(
                    date__range=date_range,
                    is_played=True,
                    status='Match Finished',
                    home_score__isnull=False,
                    away_score__isnull=False,
                    home_score=F('away_score')
                )
                .annotate(week=TruncWeek('date'))
                .values('week')
                .annotate(
                    gp_plus_sum=Sum(F('home_team_gp_plus') + F('away_team_gp_plus'))
                )
            )
            for item in stats:
                week_key = get_week_key(item)
                combined_stats[week_key] = combined_stats.get(week_key, Decimal('0.00')) + (
                            item['gp_plus_sum'] or Decimal('0.00'))

        process_gp(Fixture)
        process_gp(ArchivedFixture)

        # Build complete dictionary for all weeks in range
        result = {}
        curr = oldest_monday
        while curr <= newest_sunday:
            total_gp = combined_stats.get(curr, Decimal('0.00'))
            result[curr] = round(total_gp, 3)
            curr += timedelta(weeks=1)

        return result

    @staticmethod
    def get_bulk_weekly_plus_earned(oldest_monday, newest_sunday):
        """
        Calculates the sum of home_team_plus + away_team_plus for
        fixtures where status='Match Finished', is_played=True, and is_draw=True,
        across both models, grouped by week.
        """
        date_range = [oldest_monday, newest_sunday + timedelta(days=1)]

        def get_week_key(item):
            w = item['week']
            return w.date() if hasattr(w, 'date') else w

        combined_stats = {}

        # Helper to aggregate GP plus data
        def process_gp(qs_class):
            stats = (
                qs_class.objects.filter(
                    date__range=date_range,
                    is_played=True,
                    status='Match Finished',
                    home_score__isnull=False,
                    away_score__isnull=False,
                    home_score=F('away_score')
                )
                .annotate(week=TruncWeek('date'))
                .values('week')
                .annotate(
                    plus_earned=Sum(F('home_team_plus') + F('away_team_plus'))
                )
            )
            for item in stats:
                week_key = get_week_key(item)
                combined_stats[week_key] = (combined_stats.get(week_key, Decimal('0.00'))
                                            + (item['plus_earned'] or Decimal('0.00')))

        process_gp(Fixture)
        process_gp(ArchivedFixture)

        # Build complete dictionary for all weeks in range
        result = {}
        curr = oldest_monday
        while curr <= newest_sunday:
            total_gp = combined_stats.get(curr, Decimal('0.00'))
            result[curr] = total_gp
            curr += timedelta(weeks=1)

        return result

    @staticmethod
    def get_bulk_plus_used(oldest_monday, newest_sunday):
        """
        Calculates the sum of plus_used + manual_plus_used for every
        recoverfixture entry grouped by week.
        """
        date_range = [oldest_monday, newest_sunday + timedelta(days=1)]

        def get_week_key(item):
            w = item['week']
            return w.date() if hasattr(w, 'date') else w

        combined_stats = {}

        # Helper to aggregate GP plus data
        def process_plus_used(qs_class):

            stats = (
                qs_class.objects.filter(date__range=date_range, value_type__in=['plus', 'manual_plus'])
                .annotate(week=TruncWeek('date'))
                .values('week')
                .annotate(plus_used=Sum('value')))

            for item in stats:
                week_key = get_week_key(item)
                combined_stats[week_key] = (combined_stats.get(week_key, Decimal('0.00'))
                                            + (item['plus_used'] or Decimal('0.00')))

        process_plus_used(RecoverFixture)

        # Build complete dictionary for all weeks in range
        result = {}
        curr = oldest_monday
        while curr <= newest_sunday:
            plus_used = combined_stats.get(curr, Decimal('0.00'))
            result[curr] = plus_used
            curr += timedelta(weeks=1)

        return result




