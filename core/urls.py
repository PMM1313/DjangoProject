# core/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='home'),
    path('dashboard/', views.dashboard, name='dashboard'),

    # for the checkbox hide show recovered
    path('api/recovery-data/', views.get_recovery_data, name='get_recovery_data'),

    # HTMX Partials (Grouped for clarity)
    path('partial/fixtures/', views.fixtures_partial, name='fixtures_partial'),
    path("teams/list-partial/", views.teams_list_partial, name="teams_list_partial"),

    # Teams Logic
    path("teams/", views.TeamListCreateView.as_view(), name="team-list-create"),
    path("teams/<int:team_id>/", views.TeamDetailView.as_view(), name="team-detail"),

    path('team/fixtures/<int:team_id>/', views.team_fixtures_view, name='team_fixtures'),

    # Fixtures & Match Logic
    path('fixture/add-manual/', views.add_manual_fixture, name='add_manual_fixture'),
    path("fixtures/sync/", views.fetch_and_save_fixtures, name="fetch-and-save-fixtures"),
    path('fixture/delete/<int:fixture_id>/', views.delete_fixture, name='delete_fixture'),
    path('fixture/play/<int:fixture_id>/', views.play_match, name='play_match'),
    path('fixture/resolve-match/<int:fixture_id>/', views.resolve_match_view, name='resolve_match'),
    path('fixture/settle/<int:fixture_id>/', views.settle_fixture_manual, name='settle_fixture_manual'),
    path('fixture/confirm-settle/<str:fixture_id>/', views.confirm_manual_settle, name='confirm_manual_settle'),
    path('fixture/result-and-status/', views.results_and_statuses_view, name='fetch_scores_and_statuses'),

    # for recoveries table in the fixtures tab
    # Used by hx-trigger="load" to render the initial table
    path('get-distribution-partial/', views.get_distribution_partial, name='get_distribution_partial'),
    # Used by your creation form submission
    path('for-distribution/', views.for_distribution_view, name='for_distribution'),

    # distribution tab
    path('teams/distribution/', views.teams_distribution_view, name='distribution_table'),

    path('equalize-in-range/', views.equalize_in_range, name='equalize_in_range'),


    path('alpine-playground/', views.alpine_playground, name='alpine_playground'),
    path('streaks/', views.get_streaks, name='get_streaks'),

    # 1. The Main Tab Wrapper (Loads the stats, search bar, and initial table)
    path('leagues-tab/', views.leagues_tab_page, name='leagues_tab_page'),

    path('imports-tab/', views.imports_tab_page, name='imports_tab_page'),
    # The new target receiver endpoint pattern
    path('imports/save-manual-mappings/', views.save_manual_mappings, name='save_manual_mappings'),

    # path('save-mappings/', views.save_mappings, name='save_single_mapping'),
    # 2. The Partial Update (Only returns <tr> tags for searching/filtering)
    path('leagues-list-partial/', views.leagues_list_partial, name='leagues_list_partial'),
    path('search-external-leagues/', views.search_external_leagues, name='search_external_leagues'),
    path('save-league-from-api/', views.save_league_from_api, name='save_league_from_api'),
    path('change-league-status/', views.change_league_used_or_not, name='change_league_used_or_not'),
    path('leagues/<int:league_id>/toggle-regular/', views.toggle_regular_league, name='toggle_regular_league'),

    # adding manual plus to for recover entry
    path('update_recovery_amount_manual_plus/', views.update_recovery_amount, name='update_recovery_amount_manual_plus'),

    # extension data
    path('api/data/', views.receive_data, name='receive_data'),
]
#     # List all teams / Create a new team
#     path("teams/", TeamListCreateView.as_view(), name="team-list-create"),
#
#     # Retrieve / Delete a team by team_id
#     path("teams/<int:team_id>/", TeamDetailView.as_view(), name="team-detail"),
#     path("teams/get_all_teams/", teams_list_partial, name="teams_list_partial"),
#     path("fixtures/sync/", fetch_and_save_fixtures, name="fetch-and-save-fixtures"),
#     path('fixture/delete/<int:pk>/', delete_fixture, name='delete_fixture'),
#     path('api/fixture/play/<int:pk>/', play_match, name='play_match'),
#     path('fixture/resolve-match/<int:pk>/', resolve_match_view, name='resolve_match'),
#     path('fixture/result-and-status/', results_and_statuses_view, name='fetch_scores_and_statuses'),
#     path('team/fixtures/<int:team_id>/', team_fixtures_view, name='team_fixtures'),
#     path('teams/distribution/', teams_distribution_view, name='distribution_table'),
#     # path("fixtures/import/", import_fixtures_view, name="import-fixtures"),
# ]
