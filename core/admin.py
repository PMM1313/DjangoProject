from django.contrib import admin
from .models import (
    Country,
    ExternalMapping,
    League,
    Team,
    Fixture,
    Settings,
    TrackingValue,
    ArchivedFixture,
    ForRecover,
    RecoverFixture,
    ExternalMapping,
    PendingImport,
)


# Register your models here.
@admin.register(Country)
class CountryAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'flag')
    search_fields = ('name',)
    ordering = ('name',)


@admin.register(ExternalMapping)
class ExternalMappingAdmin(admin.ModelAdmin):
    list_display = ('id', 'external_name', 'content_type', 'object_id')
    search_fields = ('external_name', 'object_id')
    list_filter = ('content_type',)


@admin.register(League)
class LeagueAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'country', 'is_used', 'logo')
    list_filter = ('is_used', 'country')
    search_fields = ('name', 'id')
    list_editable = ('is_used',)  # Allows toggling is_used directly from the table view!


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'country', 'league', 'is_active', 'no_draw', 'all_bets', 'extra_bets', 'is_played')
    list_filter = ('is_active', 'is_played', 'country', 'league')
    search_fields = ('name', 'id')
    list_editable = ('is_active',)  # Quickly activate/deactivate teams in bulk


# @admin.register(Fixture)
# class FixtureAdmin(admin.ModelAdmin):
#     list_display = (
#         'fixture_id',
#         'match_display',
#         'date',
#         'league',
#         'status',
#         'is_played',
#         'is_draw_display',
#         'home_team_profit',
#         'away_team_profit',
#     )
#     list_filter = ('status', 'is_played', 'league', 'country', 'date')
#     search_fields = (
#         'fixture_id',
#         'api_sport_id',
#         'home_team_name',
#         'away_team_name',
#         'home_id',
#         'away_id',
#     )
#     date_hierarchy = 'date'
#     ordering = ('-date',)
#
#     # Custom callable method to display the match name
#     @admin.display(description='Match')
#     def match_display(self, obj):
#         return f"{obj.home_team_name} vs {obj.away_team_name}"
#
#     # Displays the model @property 'is_draw' safely in the list view
#     @admin.display(description='Is Draw', boolean=True)
#     def is_draw_display(self, obj):
#         return obj.is_draw


# @admin.register(TrackingValue)
# class TrackingValueAdmin(admin.ModelAdmin):
#     list_display = ('id', 'date', 'category', 'amount')
#     list_filter = ('category', 'date')
#     search_fields = ('category',)
#     date_hierarchy = 'date'
#     ordering = ('-date',)


@admin.register(Settings)
class SettingsAdmin(admin.ModelAdmin):
    list_display = ('id', 'use_plus_for_recover')


@admin.register(ArchivedFixture)
class ArchivedFixtureAdmin(admin.ModelAdmin):
    # Key columns to display in the table view
    list_display = (
        'id',
        'match_display',
        'score_display',
        'is_draw',
        'league_name',
        'date',
        'archived_at',
    )

    # Sidebar filters for fast narrowing down
    list_filter = (
        'is_draw',
        'league',
        'country',
        'season',
        'status',
        'date',
    )

    # Search bar across teams, fixture IDs, and leagues
    search_fields = (
        'home_team_name',
        'away_team_name',
        'home_id',
        'away_id',
        'fixture_id',
        'api_sport_id',
        'league_name',
    )

    # Add interactive timeline navigation at the top of the table
    date_hierarchy = 'date'

    # Default sorting (newest archived matches first)
    ordering = ('-date',)

    # Display read-only for auto-generated fields in the edit form
    readonly_fields = ('archived_at',)

    # -------------------------------------------------------------
    # Disable Manual Creation, Editing, and Deletion in Admin
    # -------------------------------------------------------------
    def has_add_permission(self, request):
        """Removes the 'ADD ARCHIVED FIXTURE' button."""
        return False

    def has_change_permission(self, request, obj=None):
        """Makes existing records read-only in the admin panel."""
        return False

    def has_delete_permission(self, request, obj=None):
        """Prevents manual deletion from the admin panel."""
        return False

    # Custom methods for cleaner list formatting
    @admin.display(description='Match')
    def match_display(self, obj):
        return f"{obj.home_team_name} vs {obj.away_team_name}"

    @admin.display(description='Score (FT)')
    def score_display(self, obj):
        return f"{obj.home_score} - {obj.away_score}"
