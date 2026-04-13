from decimal import Decimal


from django.db import models

from django.db.models import Sum, Q, DecimalField
from django.db.models.functions import Coalesce


class Country(models.Model):
    name = models.CharField(max_length=30, unique=True)
    flag = models.FileField(upload_to='countries/flags/', null=True, blank=True)

    def __str__(self):
        return self.name


class League(models.Model):
    # If you try to delete a Country, PROTECT stops you if Leagues still exist
    id = models.PositiveIntegerField(primary_key=True)  # custom PK
    country = models.ForeignKey(Country, on_delete=models.PROTECT)
    name = models.CharField(max_length=30)
    in_season = models.BooleanField(default=False)
    season_start = models.DateField(null=True, blank=True, default=None)
    season_end = models.DateField(null=True, blank=True, default=None)
    season_year = models.PositiveIntegerField(null=True, blank=True, default=None)
    is_used = models.BooleanField(default=False)
    last_updated_date = models.DateField(null=True, blank=True, default=None)
    logo = models.ImageField(upload_to='leagues/logos/', null=True, blank=True)

    def __str__(self):
        return f"{self.name} ({self.country.name})"


class Team(models.Model):
    id = models.IntegerField(primary_key=True)  # from API
    name = models.CharField(max_length=50)
    is_active = models.BooleanField(default=True)
    # PROTECT ensures you can't delete a League/Country that has active teams
    country = models.ForeignKey(Country, on_delete=models.PROTECT, null=True, blank=True)
    league = models.ForeignKey(League, on_delete=models.PROTECT, null=True, blank=True)

    all_bets = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    extra_bets = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    last_played_date = models.DateField(null=True, blank=True, default=None)
    no_draw = models.IntegerField(null=True, blank=True)

    # Add these lines to tell your editor about the related names
    home_fixtures: models.Manager['Fixture']
    away_fixtures: models.Manager['Fixture']

    def __str__(self):
        return self.name

    def get_fixtures(self):
        return {
            'current': Fixture.objects.filter(
                Q(home_id=self.id) | Q(away_id=self.id)
            ).order_by('-date'),

            'archived': ArchivedFixture.objects.filter(
                Q(home_id=self.id) | Q(away_id=self.id)
            ).order_by('-date')
        }

    @classmethod
    def get_total_all_bets(cls):
        """Calculates the sum of all_bets for every team in the table."""
        result = cls.objects.aggregate(
            total=Coalesce(
                Sum('all_bets'),
                0,
                output_field=DecimalField()
            )
        )
        return result['total']


class Fixture(models.Model):
    api_sport_id = models.IntegerField(db_index=True, default=0)  # api sport fixture id
    fixture_id = models.BigIntegerField(unique=True, db_index=True, default=0)  # I generate this
    # Related names must be unique so Django knows which is which
    home_id = models.IntegerField()
    away_id = models.IntegerField()
    # home_team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='home_fixtures')
    # away_team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='away_fixtures')
    home_team_name = models.CharField(max_length=50)
    away_team_name = models.CharField(max_length=50)
    home_team_bet = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    away_team_bet = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)

    home_team_money_to_recover = models.DecimalField(max_digits=7, decimal_places=2, default='0.00')
    away_team_money_to_recover = models.DecimalField(max_digits=7, decimal_places=2, default='0.00')
    home_team_entry_for_recovery_with_bet = models.IntegerField(default=0)  # the entry in forrecover table
    away_team_entry_for_recovery_with_bet = models.IntegerField(default=0)  # the entry in forrecover table

    home_team_profit = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    away_team_profit = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    home_team_plus = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    away_team_plus = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)

    home_team_plus_used_for_recovery = models.BooleanField(default=False)
    away_team_plus_used_for_recovery = models.BooleanField(default=False)

    league = models.ForeignKey(League, on_delete=models.PROTECT)
    country = models.ForeignKey(Country, on_delete=models.PROTECT)
    coefficient = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    is_played = models.BooleanField(default=False)
    status = models.CharField(max_length=20, default="Not Started")
    date = models.DateTimeField()
    home_score = models.IntegerField(null=True, blank=True)
    away_score = models.IntegerField(null=True, blank=True)

    season = models.PositiveIntegerField()

    class Meta:
        # This ensures that whenever you query Fixtures,
        # they are automatically sorted by date and time.
        ordering = ['date']

    @property
    def is_draw(self):
        is_draw = self.home_score == self.away_score
        return is_draw

    @property
    def total_fixture_bet(self):
        # Use 'or 0' to handle cases where the match hasn't been played yet
        h_bet = self.home_team_bet or Decimal('0')
        a_bet = self.away_team_bet or Decimal('0')

        return h_bet + a_bet

    @property
    def can_be_resolved(self):
        # 1. Check if the match is played
        # 2. Check the status string
        # 3. Ensure scores are not None (NULL in DB)
        return (
                self.is_played and
                self.status == 'Match Finished' and
                self.home_score is not None and
                self.away_score is not None
        )

    @property
    def does_teams_have_played_fixtures(self):
        not_settled_fixtures = Fixture.objects.filter(
            Q(home_id=self.home_id) | Q(away_id=self.home_id) |
            Q(home_id=self.away_id) | Q(away_id=self.away_id),
            is_played=True
        ).exclude(id=self.pk).order_by('-date')

        # teams doesnt have other not settled fixtures
        if not not_settled_fixtures:
            return ''

        messages = []
        for fixture in not_settled_fixtures:
            # Determine which team is the culprit
            if fixture.home_id == self.home_id or fixture.away_id == self.home_id:
                team_name = self.home_team_name
            else:
                team_name = self.away_team_name

            # Format the date (e.g., "Jan 27")
            date_str = fixture.date.strftime("%b %d")
            messages.append(f"{team_name} played on {date_str}")

        # Join multiple conflicts with a comma or separator
        return "Already played: " + ", ".join(set(messages))

    @classmethod
    def get_total_live_bets(cls):
        """
        Calculates the sum of all home_team_bet and away_team_bet
        across the entire database.
        """
        totals = cls.objects.aggregate(
            all_home_bets=Coalesce(
                Sum('home_team_bet'),
                0,
                output_field=DecimalField()
            ),
            all_away_bets=Coalesce(
                Sum('away_team_bet'),
                0,
                output_field=DecimalField()
            )
        )
        # Sum the two results together
        return totals['all_home_bets'] + totals['all_away_bets']

    def __str__(self):
        home_name = self.home_team_name if self.home_team_name else "Unknown"
        away_name = self.away_team_name if self.away_team_name else "Unknown"
        return f"{home_name} vs {away_name} ({self.date})"


class ArchivedFixture(models.Model):
    api_sport_id = models.IntegerField(db_index=True, default=0)  # api sport fixture id
    fixture_id = models.BigIntegerField(db_index=True, null=True, blank=True)  # I generate this
    # Keep the core data
    home_team_name = models.CharField(max_length=50)
    away_team_name = models.CharField(max_length=50)

    # Financial results
    home_id = models.IntegerField(db_index=True)
    away_id = models.IntegerField(db_index=True)
    home_team_bet = models.DecimalField(max_digits=7, decimal_places=2)
    away_team_bet = models.DecimalField(max_digits=7, decimal_places=2)
    home_team_profit = models.DecimalField(max_digits=7, decimal_places=2)
    away_team_profit = models.DecimalField(max_digits=7, decimal_places=2)
    home_team_plus = models.DecimalField(max_digits=5, decimal_places=2)
    away_team_plus = models.DecimalField(max_digits=5, decimal_places=2)

    home_team_money_to_recover = models.DecimalField(max_digits=7, decimal_places=2, default='0.00')
    away_team_money_to_recover = models.DecimalField(max_digits=7, decimal_places=2, default='0.00')
    home_team_entry_for_recovery_with_bet = models.IntegerField(default=0)
    away_team_entry_for_recovery_with_bet = models.IntegerField(default=0)

    # home_team_plus_used_to_recover = models.DecimalField(max_digits=7, decimal_places=2, default='0.00')
    # away_team_plus_used_to_recover = models.DecimalField(max_digits=7, decimal_places=2, default='0.00')
    # home_team_entry_for_recovery_with_plus = models.IntegerField(default=0)  # the entry in forrecover table
    # away_team_entry_for_recovery_with_plus = models.IntegerField(default=0)  # the entry in forrecover table
    home_team_plus_used_for_recovery = models.BooleanField(default=False)
    away_team_plus_used_for_recovery = models.BooleanField(default=False)

    # Match Details
    coefficient = models.DecimalField(max_digits=5, decimal_places=2)
    home_score = models.IntegerField()
    away_score = models.IntegerField()
    is_draw = models.BooleanField()
    date = models.DateTimeField()
    league_name = models.CharField(max_length=100)  # Store name as string for archive
    league = models.ForeignKey(League, on_delete=models.PROTECT, null=True, blank=True)
    country = models.ForeignKey(Country, on_delete=models.PROTECT, null=True, blank=True)
    season = models.PositiveIntegerField(null=True, blank=True)
    status = models.CharField(max_length=20, null=True, blank=True)
    is_played = models.BooleanField(null=True, blank=True)
    archived_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['date']

    @staticmethod
    def get_team_history(team_id):
        # This finds all matches where the team was either Home or Away
        history = ArchivedFixture.objects.filter(
            Q(home_id=team_id) | Q(away_id=team_id)
        ).order_by('date')  # Sort by newest date first

        return history


class Settings(models.Model):
    # Your single stats
    min_bet = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True, help_text="Minimum bet")
    avg_perc_draw = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True,
                                        help_text="Average percentage draw per round")
    rounds_for_earning_back = models.IntegerField(default=0, help_text="Round to earn back")
    use_plus_for_recover = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Settings"
        verbose_name_plural = "Settings"

    def save(self, *args, **kwargs):
        """
        Forces the primary key to 1. No matter how many times
        'save' is called, it will only ever update the first row.
        """
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """
        Optional: Prevents deleting the settings row
        to ensure the app always has data.
        """
        pass

    @classmethod
    def load(cls):
        """
        The key helper method.
        Ensures the row exists and returns it in one go.
        """
        obj, created = cls.objects.get_or_create(pk=1)
        return obj


class TrackingValue(models.Model):
    # We define the three types here
    TYPE_CHOICES = [
        ('PROFIT', 'Profit'),
        ('BET', 'Bet'),
        ('PLUS_EARNED', 'Plus earned'),
        ('PLUS_USED', 'Plus used'),
    ]

    date = models.DateField(db_index=True)
    category = models.CharField(max_length=11, choices=TYPE_CHOICES, db_index=True)
    amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)

    class Meta:
        # This ensures we only have ONE row per date PER category
        unique_together = ('date', 'category')
        ordering = ['-date']

    @classmethod
    def get_total_available_plus(cls):
        totals = cls.objects.aggregate(
            earned=Coalesce(
                Sum('amount', filter=Q(category='PLUS_EARNED')),
                0,
                output_field=DecimalField()  # <--- Add this
            ),
            used=Coalesce(
                Sum('amount', filter=Q(category='PLUS_USED')),
                0,
                output_field=DecimalField()  # <--- Add this
            )
        )
        return totals['earned'] - totals['used']


class ForRecover(models.Model):
    id = models.AutoField(primary_key=True)
    team = models.ForeignKey(
        Team,
        on_delete=models.PROTECT,
        null=True,  # 👈 IMPORTANT
        blank=True
    )
    date_added_to_recover = models.DateTimeField(auto_now_add=True)
    # team_id = models.IntegerField(db_index=True)  # from API
    team_name = models.CharField(max_length=50)
    bets_writen_off = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    bets_recovered = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    plus_used_to_recover = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    plus_used_manual = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    fixtures_played = models.IntegerField(default=0)  # fixtures played to recover the sum
    fixtures_recovered = models.IntegerField(default=0)  # draw fixtures contributed for recovery
    # total_bets_to_recover = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    date_recovered = models.DateTimeField(null=True, blank=True, default=None)
    is_recovered = models.BooleanField(default=False)

    @property
    def bets_to_recover(self):
        bets_to_recover = self.bets_writen_off - (self.bets_recovered
                                                  + self.plus_used_to_recover
                                                  + self.plus_used_manual)
        if bets_to_recover < Decimal('0.00'):
            bets_to_recover = Decimal('0.00')
        return bets_to_recover

    @staticmethod
    def get_all_recovery_data():
        recoveries = ForRecover.objects.all().order_by('date_added_to_recover')

        return recoveries


class RecoverFixture(models.Model):

    for_recover = models.ForeignKey(
        ForRecover,
        on_delete=models.CASCADE,
        related_name="fixtures_for_recover"
    )

    fixture_id = models.BigIntegerField(db_index=True, null=True, blank=True)

    team = models.ForeignKey(Team, on_delete=models.SET_NULL, null=True, blank=True)
    value = models.DecimalField(max_digits=10, decimal_places=2)
    date = models.DateTimeField(auto_now_add=True, db_index=True)

    VALUE_TYPES = (
        ("bet", "Bet"),
        ("plus", "Plus"),
        ("manual_plus", "Manual Plus"),
    )

    value_type = models.CharField(max_length=12, choices=VALUE_TYPES)

    class Meta:
        indexes = [
            models.Index(fields=["fixture_id"]),
            models.Index(fields=["for_recover"]),
        ]

    @property
    def fixture_data(self):
        # First look in active Fixtures
        fixture = Fixture.objects.filter(fixture_id=self.fixture_id).first()
        if fixture:
            return fixture
        # If not found, look in Archived
        return ArchivedFixture.objects.filter(fixture_id=self.fixture_id).first()

