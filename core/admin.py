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
    PendingImport, ConstanceAuditLog,
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


@admin.register(TrackingValue)
class TrackingValueAdmin(admin.ModelAdmin):
    # Columns shown in the list view
    list_display = ('date', 'category', 'amount')

    # Sidebar filters for quick navigation
    list_filter = ('category', 'date')

    # Enable search by category name
    search_fields = ('category',)

    # Default ordering in the admin list
    ordering = ('-date', 'category')


@admin.register(Settings)
class SettingsAdmin(admin.ModelAdmin):
    list_display = (
        '__str__',
        'min_bet',
        'avg_coefficient',
        'avg_perc_draw',
        'rounds_for_earning_back',
        'use_plus_for_recover'
    )

    # Prevent adding more than 1 Settings instance from the admin UI
    def has_add_permission(self, request):
        if Settings.objects.exists():
            return False
        return super().has_add_permission(request)

    # Prevent deleting the single Settings instance
    def has_delete_permission(self, request, obj=None):
        return False


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


@admin.register(ForRecover)
class ForRecoverAdmin(admin.ModelAdmin):
    # Полетата, които да се показват като колони в списъка с обекти
    list_display = (
        'id',
        'team_name',
        'bets_writen_off',
        'gp_bets_writen_off',
        'bets_recovered',
        'gp_bets_recovered',
        'is_recovered',
        'date_added_to_recover'
    )

    # Полета, които да бъдат линкове към детайлния изглед за редакция
    list_display_links = ('id', 'team_name')

    # Филтри в дясната лента на административния панел
    list_filter = ('is_recovered', 'date_added_to_recover')

    # Полета, по които може да се търси през горната търсачка
    search_fields = ('team_name', 'team__name')

    # Полета само за четене (ако не искаш да се променят ръчно, например датите)
    readonly_fields = ('date_added_to_recover', 'date_recovered')


@admin.register(Fixture)
class FixtureAdmin(admin.ModelAdmin):
    # Данните, които се показват като колони на главния екран (списъка)
    list_display = (
        'fixture_id',
        'date',
        'home_team_name',
        'away_team_name',
        'home_score',
        'away_score',
        'status',
        'is_played',
        'league',
        'season',
    )

    # Колоните, които да служат като линк към детайлната форма за редакция
    list_display_links = ('fixture_id', 'home_team_name', 'away_team_name')

    # Филтри в дясната лента за бързо сортиране
    list_filter = (
        'is_played',
        'status',
        'league',
        'country',
        'season',
        'date'
    )

    # Полета за търсене в горната част на екрана
    search_fields = (
        'home_team_name',
        'away_team_name',
        'fixture_id',
        'api_sport_id',
        'league__name',
        'country__name'
    )

    # Изискуеми readonly полета за @property методите ти,
    # за да се виждат коректно на екрана при редакция на обекта:
    readonly_fields = (
        'total_fixture_bet',
        'can_be_resolved',
        'does_teams_have_played_fixtures',
        'is_draw',
    )

    # Организиране на всички полета в логически секции при клик и редакция на обект
    fieldsets = (
        ('Идентификатори и Дата', {
            'fields': ('fixture_id', 'api_sport_id', 'season', 'date')
        }),
        ('Отбори, Първенство и Коефициенти', {
            'fields': (
                'home_id', 'away_id',
                'home_team_name', 'away_team_name',
                'league', 'league_round', 'country',
                'coefficient', 'home_n_play', 'away_n_play'
            )
        }),
        ('Резултат и Статус на Мача', {
            'fields': ('is_played', 'status', 'home_score', 'away_score', 'is_draw')
        }),
        ('Финансови данни (Залози и Печалби)', {
            'fields': (
                'home_team_bet', 'away_team_bet',
                'home_team_profit', 'away_team_profit',
                'home_team_plus', 'away_team_plus',
                'total_fixture_bet'
            )
        }),
        ('Guaranteed Plus (GP) и Възстановяване', {
            'fields': (
                'home_team_gp_bet', 'away_team_gp_bet',
                'home_team_gp_plus', 'away_team_gp_plus',
                'home_team_money_to_recover', 'away_team_money_to_recover',
                'home_team_entry_for_recovery_with_bet', 'away_team_entry_for_recovery_with_bet',
                'home_team_plus_used_for_recovery', 'away_team_plus_used_for_recovery'
            )
        }),
        ('Валидация и Източници', {
            'fields': ('can_be_resolved', 'does_teams_have_played_fixtures', 'sources')
        }),
    )


@admin.register(ConstanceAuditLog)
class ConstanceAuditLogAdmin(admin.ModelAdmin):


    list_display = ('key', 'old_value', 'new_value', 'changed_at')
    list_filter = ('key', 'changed_at')
    search_fields = ('key', 'old_value', 'new_value')

    readonly_fields = ('changed_at',)
