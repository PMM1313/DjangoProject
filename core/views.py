import json
import traceback

from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from _decimal import InvalidOperation
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal

from django.contrib import messages
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.db.models import OuterRef, Exists, Q, Subquery, Max
from django.http import HttpResponseBadRequest, JsonResponse, HttpResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.core.exceptions import ObjectDoesNotExist
# Create your views here.
from django.template.loader import render_to_string
from django.views.decorators.http import require_http_methods, require_POST, require_GET
from rest_framework.views import APIView
from django.http import Http404
from rest_framework.response import Response
from rest_framework import status, generics

from .forms import ManualFixtureForm, SettleFixtureForm
from .models import Team, Fixture, ForRecover, League, Country, TrackingValue, RecoverFixture, PendingImport, \
    ExternalMapping
from .serializers import TeamSerializer

# -------------------------------
# List all teams / Create a new team
# -------------------------------
from .services.fixture import FixtureService
from .services.team import TeamService
from .services.for_recover import format_recovery_data
from .services import for_recover
from .services.league import LeagueService
from .services.stats import TrackingValues


class TeamListCreateView(LoginRequiredMixin, APIView):
    def get(self, request):
        teams = Team.objects.all()
        serializer = TeamSerializer(teams, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        serializer = TeamSerializer(data=request.data)
        if serializer.is_valid():
            team_id = serializer.validated_data['team_id']
            if Team.objects.filter(team_id=team_id).exists():
                return Response(
                    {"error": f"Team with team_id {team_id} already exists."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        # Return validation errors
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# -------------------------------
# Retrieve / Delete a single team
# -------------------------------
class TeamDetailView(LoginRequiredMixin, APIView):
    def get(self, request, team_id):
        # Fetch the team, return 404 if not found
        team = Team.objects.filter(team_id=team_id).first()
        if not team:
            return Response(
                {"error": f"Team with team_id {team_id} does not exist."},
                status=status.HTTP_404_NOT_FOUND
            )
        serializer = TeamSerializer(team)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def delete(self, request, team_id):
        team = Team.objects.filter(team_id=team_id).first()
        if not team:
            return Response(
                {"error": f"Team with team_id {team_id} does not exist."},
                status=status.HTTP_404_NOT_FOUND
            )
        team_name = team.team_name
        team.delete()
        return Response(
            {"message": f"Team '{team_name}' deleted successfully."},
            status=status.HTTP_200_OK
        )

    def patch(self, request, team_id):
        team = get_object_or_404(Team, team_id=team_id)
        serializer = TeamSerializer(team, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(
                {"message": f"Team '{team.team_name}' updated successfully.",
                 "team": serializer.data},
                status=status.HTTP_200_OK
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@login_required
def dashboard(request):
    # Fetch the raw data (Model)
    queryset = ForRecover.objects.all().order_by('date_added_to_recover')

    # Format the data (Service)
    initial_data = format_recovery_data(queryset)

    # for the stats
    stats = TrackingValue.get_total_available_plus()
    live_bets = Fixture.get_total_live_bets()
    teams_bets = Team.get_total_all_bets()

    return render(request, 'dashboard.html', {
        'user_name': request.user.username,
        'first_name': request.user.first_name,
        'total_count': Team.objects.count(),
        'initial_recoveries': initial_data,
        'stats': stats,
        'live_bets': live_bets,
        'teams_bets': teams_bets,
    })


@login_required
def get_recovery_data(request):
    """The AJAX endpoint for your Alpine.js checkbox"""
    show_all = request.GET.get('show_all') == 'true'

    if show_all:
        queryset = ForRecover.objects.all()
    else:
        queryset = ForRecover.objects.filter(is_recovered=False)

    data = format_recovery_data(queryset.order_by('date_added_to_recover'))
    return JsonResponse(data, safe=False)


@login_required
def fixtures_partial(request):
    # Call directly on the Class
    data = FixtureService.get_grouped_fixtures()

    return render(request, 'includes/_fixture_table.html', {
        'grouped_fixtures': data
    })


@login_required
def teams_list_partial(request):
    # Subquery 1: The "Live" fixture (is_played=True)
    live_fixture = Fixture.objects.filter(
        Q(home_id=OuterRef('id')) | Q(away_id=OuterRef('id')),
        is_played=True
    ).order_by('-date')  # Get the most recent live one

    # Subquery 2: The "Upcoming" fixture (is_played=False)
    upcoming_fixture = Fixture.objects.filter(
        Q(home_id=OuterRef('id')) | Q(away_id=OuterRef('id')),
        is_played=False
    ).order_by('date')  # Get the soonest upcoming one

    teams = Team.objects.select_related('country', 'league').annotate(
        # Live Data
        live_date=Subquery(live_fixture.values('date')[:1]),
        live_home=Subquery(live_fixture.values('home_team_name')[:1]),
        live_away=Subquery(live_fixture.values('away_team_name')[:1]),

        # Upcoming Data
        next_date=Subquery(upcoming_fixture.values('date')[:1]),
        next_home=Subquery(upcoming_fixture.values('home_team_name')[:1]),
        next_away=Subquery(upcoming_fixture.values('away_team_name')[:1]),
    ).all().order_by('name')

    return render(request, 'partials/teams_table.html', {'teams': teams})


@login_required
def fetch_and_save_fixtures(request):
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    date_from = request.POST.get("date_from")
    date_to = request.POST.get("date_to")

    print("✅ fetch_and_save_fixtures VIEW HIT")
    print(f"📅 Range: {date_from} → {date_to}")

    try:
        # If fetch_and_save is an instance method:
        service = FixtureService()
        summary = service.fetch_and_save_fixtures(date_from, date_to)

        # But we call the static helper directly:
        grouped_data = FixtureService.get_grouped_fixtures()

        html = render_to_string('includes/_fixture_table.html', {
            'grouped_fixtures': grouped_data
        })

        response = HttpResponse(html)

        # Craft a contextual toast message based on results
        if summary.get("errors"):
            failed_count = len(summary["errors"])
            toast_text = f"Saved {summary['created']} fixtures, but {failed_count} failed."
            toast_level = "error"
        else:
            toast_text = f"Successfully updated {summary['created']} fixtures!"
            toast_level = "success"

        # We manually add your custom trigger to the HTML response
        # so the toast pops up along with the new table
        response["HX-Trigger"] = json.dumps({
            "showToast": {
                "text": toast_text,
                "level": toast_level
            }
        })
        return response

    except Exception as e:
        print(f"❌ View-level error: {e}")

        # ERROR: Use your specific toast_response helper
        # We pass the error message and the 'error' level

        return toast_response(
            message=str(e),
            level="error",
            status_code=200  # We keep 200 so HTMX processes the trigger
        )


@login_required
@transaction.atomic
def add_manual_fixture(request):
    if request.method == "POST":
        form = ManualFixtureForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            h_team = data['home_team']
            a_team = data['away_team']

            # 1. Handle Timezone-aware Datetime (Safe Version)
            naive_dt = datetime.combine(data['date'], data['start_time'])
            if timezone.is_naive(naive_dt):
                fixture_dt = timezone.make_aware(naive_dt)
            else:
                fixture_dt = naive_dt

            # 2. Use your custom ID generator
            generated_id = FixtureService.generate_fixture_id(
                date_obj=data['date'],
                home_id=h_team.id,
                away_id=a_team.id,
                year=None
            )

            # 3. Create the Fixture
            fixture = Fixture.objects.create(
                api_sport_id=0,
                fixture_id=generated_id,
                home_id=h_team.id,
                away_id=a_team.id,
                home_team_name=h_team.name,
                away_team_name=a_team.name,
                league=data['league'],
                country=data['country'],
                date=fixture_dt,
                status="Not Started",
                season=data['season'],
            )

            # 4. Return toast AND trigger a table refresh
            # Assuming your Alpine store/table listens for 'refreshFixtures'
            response = toast_response("Fixture added!", level="success")

            # Use .get() in case HX-Trigger is missing for some reason
            trigger_data = response.get("HX-Trigger", "{}")
            # If it's a string (standard), load it; if it's already a dict, use it
            triggers = json.loads(trigger_data) if isinstance(trigger_data, str) else trigger_data

            triggers["refreshFixtures"] = True
            response["HX-Trigger"] = json.dumps(triggers)

            return response

    return render(request, 'partials/manual_fixture_form.html', {'form': ManualFixtureForm()})


@login_required
@transaction.atomic
def settle_fixture_manual(request, fixture_id):
    # 1. Fetch the fixture object from the database using the ID from the URL
    fixture = get_object_or_404(Fixture, fixture_id=fixture_id)

    # 2. Pass it to the template as 'f'
    return render(request, 'partials/settle_fixture_form.html', {
        'f': fixture
    })


@login_required
@transaction.atomic
def confirm_manual_settle(request, fixture_id):
    try:
        fixture_id_int = int(fixture_id)
    except (ValueError, TypeError):
        raise Http404("Invalid fixture ID format")

        # Query using the verified integer
    fixture = get_object_or_404(Fixture, fixture_id=fixture_id_int)

    if request.method == "POST":
        fixture.home_score = request.POST.get('home_score')
        fixture.away_score = request.POST.get('away_score')
        fixture.status = request.POST.get('status')
        fixture.save()

    # Return the original row template so the inputs disappear
    # and the new scores show up in the normal table layout
    return render(request, 'partials/fixture_row.html', {'f': fixture})


@login_required  # Ensures only logged-in users can delete
@transaction.atomic  # Ensures the DB stays consistent if deletion is complex
@require_http_methods(["DELETE"])
def delete_fixture(request, fixture_id):
    try:
        fixture = Fixture.objects.get(fixture_id=fixture_id)
        fixture.delete()
        data = {"text": "Fixture deleted successfully!", "level": "success"}
        status_code = 200
    except ObjectDoesNotExist:
        data = {"text": "Fixture not found in DB.", "level": "warning"}
        status_code = 200  # Still 200 so HTMX removes the row
    except Exception as e:
        # This catches "Real Errors" (DB down, disk full, etc.)
        data = {"text": "Server Error: Could not delete.", "level": "error"}
        status_code = 500  # Tell HTMX/Browser something actually broke

    response = HttpResponse("", status=status_code)
    response['HX-Trigger'] = json.dumps({"showToast": data})
    return response


@login_required  # Ensures only logged-in users can play
@transaction.atomic
def play_match(request, fixture_id):
    fixture_obj = get_object_or_404(Fixture, fixture_id=fixture_id)

    conflict_msg = fixture_obj.does_teams_have_played_fixtures
    if conflict_msg:
        response = HttpResponse(status=204)
        response['HX-Trigger'] = json.dumps({
            "showToast": {
                "text": f"Cannot play: {conflict_msg}",
                "level": "error"
            }
        })
        return response

    coef = request.POST.get('coefficient')
    fixture = FixtureService.play_match(fixture_id, coef)

    html = render_to_string("partials/fixture_row.html", {"f": fixture}, request=request)
    response = HttpResponse(html)
    response['HX-Trigger'] = json.dumps({
        "showToast": {"text": f"Match {fixture.home_team_name} vs {fixture.away_team_name} played!", "level": "success"}
    })
    return response


@login_required
@require_POST
def resolve_match_view(request, fixture_id):
    try:
        # Execute business logic
        FixtureService.resolve_fixture(fixture_id)

        # Success: 200 OK + empty response -> HTMX deletes the row
        return HttpResponse("")

    except ValueError as e:
        # Catch expected errors (e.g., item not found / invalid state)
        # Returns HTTP 400 so HTMX cancels the row deletion
        return HttpResponseBadRequest(str(e))

    except Exception:
        # Catch unexpected server errors
        return HttpResponse("An error occurred while resolving the match.", status=500)


@login_required
def results_and_statuses_view(request):
    # .1 Fetch scores and statuses
    service = FixtureService()

    # We don't want a single day's error to show a 500 page
    try:
        # Run the fetch and get the summary report
        summary = service.fetch_scores_and_statuses()

    except Exception as e:
        # This would only trigger if the loop itself fails (not the API calls)
        print(f"Critical Sync Error: {e}")

    # Build the Toast Message
    if not summary['error_dates']:
        msg = f"Successfully updated {summary['updated_count']} fixtures."
        lvl = "success"
    elif not summary['success_dates']:
        msg = f"API Error: Could not fetch any dates due to plan limits."
        lvl = "error"
    else:
        # Mixed results
        msg = f"Updated {summary['updated_count']} fixtures. (Errors on: {', '.join(summary['error_dates'])})"
        lvl = "warning"

    # .2 Get data from DB
    data = service.get_grouped_fixtures()

    # Generate the response using your helper
    response = render(request, 'includes/_fixture_table.html', {
        'grouped_fixtures': data
    })

    # Manually attach the HX-Trigger since you are returning a rendered template,
    # but still using your toast logic structure:
    response["HX-Trigger"] = json.dumps({
        "showToast": {
            "text": msg,
            "level": lvl
        }
    })

    return response


@login_required
def team_fixtures_view(request, team_id):
    # 1. Get the actual team object
    team = get_object_or_404(Team, id=team_id)

    # 2. Pass the team to the template
    # The template will call team.get_fixtures inside the {% with %} tag
    return render(request, 'partials/fixture_list.html', {'team': team})


# distribution tab
@login_required
def teams_distribution_view(request):
    # 1. Fetch all active teams
    teams = list(Team.objects.filter(is_active=True))

    # 2. Fetch ALL fixtures that are played (unsolved) in ONE hit
    # We only care about fixtures that are played but still in this table
    # played_fixtures = Fixture.objects.filter(is_played=True).order_by('-date')
    played_fixtures = Fixture.objects.order_by('-date')

    # 3. Create a map: { team_id: [fixture1, fixture2] }
    fixture_map = defaultdict(list)
    for fx in played_fixtures:
        fixture_map[fx.home_id].append(fx)
        fixture_map[fx.away_id].append(fx)

    # 4. Determine max no_draw for table headers
    max_no_draw = Team.objects.filter(is_active=True).aggregate(
        Max('no_draw'))['no_draw__max'] or 0

    # 5. Build the matrix { 0: [Team, Team], 1: [Team] ... }
    matrix = {i: [] for i in range(max_no_draw + 1)}

    for team in teams:
        # Attach the list of fixtures from our map to the team object
        team.fixtures = fixture_map.get(team.id, [])
        team.all_bets = team.all_bets

        draw_val = team.no_draw if team.no_draw is not None else 0

        matrix[draw_val].append(team)

    return render(request, 'partials/distribution_table.html', {'matrix': matrix})


@login_required
@require_GET  # <--- This handles the hx-trigger="load"
def get_distribution_partial(request):
    recoveries = ForRecover.objects.all().order_by('-date_added_to_recover')
    return render(request, "partials/_distribution_table.html", {
        "initial_recoveries": recoveries
    })


@login_required
@require_POST
# responsible when team and amount is chosen from the UI and send to server
# so chosen amount is removed from team bets and "for recover" entry is created
def for_distribution_view(request):
    team_id = request.POST.get("team_id")
    value_str = request.POST.get("for_distribution")

    # 1. Validation using your toast_response helper
    if not team_id or not value_str:
        return toast_response("Missing required data.", level="error", status_code=400)

    try:
        value = Decimal(value_str)
    except (InvalidOperation, TypeError):
        return toast_response("Invalid number format.", level="error", status_code=400)

    team = get_object_or_404(Team, id=team_id)

    # 2. Business Logic with Transaction
    try:
        with transaction.atomic():
            current_bets = team.all_bets or Decimal('0.00')
            team.all_bets = current_bets - value
            team.save()

            ForRecover.objects.create(
                team_id=team.id,
                team_name=team.name,
                bets_writen_off=value
            )

        # 3. Fetch fresh dataset for response
        recoveries = ForRecover.objects.all().order_by('-date_added_to_recover')

        context = {
            "initial_recoveries": recoveries,
        }

        # 4. Render the table component
        response = render(request, "partials/_distribution_table.html", context)

        # 5. Add both triggers to HX-Trigger header
        # - betUpdated updates the team's local Alpine balance in matrix-wrapper
        # - showToast triggers your JS notification listener
        response["HX-Trigger"] = json.dumps({
            "betUpdated": {
                "teamId": team.id,
                "amount": float(team.all_bets)
            },
            "showToast": {
                "text": f"Created entry for {team.name} successfully!",
                "level": "success"
            }
        })

        return response

    except Exception as e:
        return toast_response(f"Database error: {str(e)}", level="error", status_code=500)


@login_required
@require_POST
def update_recovery_amount_manual_plus(request):
    item_id = request.POST.get('item_id')
    amount = float(request.POST.get('amount', 0))

    # 1. Fetch and update the DB row
    recovery = ForRecover.objects.get(id=item_id)
    recovery.manual_plus += amount
    recovery.save()

    # 2. Return ONLY the single row template piece with the updated row object
    return render(request, "partials/_distribution_row.html", {"item": recovery})


def toast_response(message, level="success", status_code=200, data=None):
    """
    Helper to return a JsonResponse with HTMX toast triggers.
    Message: string
    Levels: 'success', 'error', 'info', 'warning'
    Data: for Alpine (for now used in for distribution entries)
    """
    payload = {"message": message, "status": level}
    if data is not None:
        payload["new_data"] = data  # This is what initData(data) will receive

    response = JsonResponse(payload, status=status_code)
    response["HX-Trigger"] = json.dumps({
        "showToast": {
            "text": message,
            "level": level,
            "new_data": data
        }
    })
    return response


@login_required
def alpine_playground(request):
    return render(request, 'test_playground.html')


@login_required
def get_streaks(request):
    category_data = defaultdict(list)
    teams = Team.objects.filter(is_active=True)

    for team in teams:
        # Get the current running streaks for this team
        current_stats = TeamService.calculate_team_streaks(team.id)

        for cat_key, length in current_stats.items():
            if length >= 2:  # Only bother with streaks of 2 or more
                display_names = {
                    'odd': 'Odd Score', 'even': 'Even Score',
                    'over25': 'Over 2.5 Goals', 'under25': 'Under 2.5 Goals',
                    'win': 'Win Streak', 'draw': 'Draw Streak', 'loss': 'Loss Streak'
                }
                display_name = display_names.get(cat_key, cat_key.title())

                category_data[display_name].append({
                    'team': team.name,
                    'length': length
                })

    # Sort each category by length and take top 5
    final_streaks = {}
    for category, team_list in category_data.items():
        final_streaks[category] = sorted(team_list, key=lambda x: x['length'], reverse=True)[:5]

    return render(request, 'partials/streaks_list.html', {'all_categories': final_streaks})


@login_required
def leagues_tab_page(request):
    """Loads the entire layout for the Leagues tab."""
    leagues = League.objects.select_related('country').all().order_by('name')
    active_count = leagues.filter(in_season=True).count()
    used_count = leagues.filter(is_used=True).count()

    context = {
        'leagues': leagues,
        'active_count': active_count,
        'used_count': used_count,
    }
    return render(request, 'leagues_tab/leagues_tab_page.html', context)


@login_required
def imports_tab_page(request):
    """Loads the entire layout for the Imports tab."""

    pending = PendingImport.objects.filter(is_processed=False).order_by('-created_at').first()

    if not pending:
        return HttpResponse("<p class='p-3'>No pending imports found.</p>")

    # The new structure: { "England": { "Premier League": [...] } }
    all_data = pending.data.get('matches', {})
    view_data = []

    # Get ContentTypes once to avoid repeated DB hits in the loop
    team_type = ContentType.objects.get_for_model(Team)
    league_type = ContentType.objects.get_for_model(League)
    country_type = ContentType.objects.get_for_model(Country)

    # TRIPLE LOOP: Country -> League -> Match List
    for c_name, leagues_dict in sorted(all_data.items()):

        # Process Country mapping
        mapping = ExternalMapping.objects.filter(external_name=c_name, content_type=country_type).first()
        internal_country = mapping.internal_object if mapping else Country.objects.filter(name__iexact=c_name).first()
        league_wrappers = []

        for l_name, match_list in sorted(leagues_dict.items()):

            # 2. Process League mapping
            l_mapping = ExternalMapping.objects.filter(external_name=l_name, content_type=league_type,
                                                       country=internal_country).first()
            internal_league = l_mapping.internal_object if l_mapping else League.objects.filter(name__iexact=l_name,
                                                                                                country=internal_country).first()
            match_wrappers = []

            # 3. Process Teams from Match List
            for match in match_list:
                t_home_ext = match.get('homeTeam')
                t_away_ext = match.get('awayTeam')

                if l_name == "Friendlies Clubs":
                    t_home_ext = t_home_ext.split('(')[0].strip()
                    t_away_ext = t_away_ext.split('(')[0].strip()

                # Resolve Home Team
                m_home = ExternalMapping.objects.filter(external_name=t_home_ext, country=internal_country,
                                                        content_type=team_type).first()
                home_obj = m_home.internal_object if m_home else Team.objects.filter(name__iexact=t_home_ext,
                                                                                     country=internal_country).first()

                # Resolve Away Team
                m_away = ExternalMapping.objects.filter(external_name=t_away_ext, country=internal_country,
                                                        content_type=team_type).first()
                away_obj = m_away.internal_object if m_away else Team.objects.filter(name__iexact=t_away_ext,
                                                                                     country=internal_country).first()

                # Create Match Wrapper
                match_wrappers.append({
                    'scraped': match,
                    'home_obj': home_obj,
                    'away_obj': away_obj,
                    'is_ready': home_obj is not None and away_obj is not None
                })

            # Create the League Wrapper
            league_wrappers.append({
                'external_name': l_name,
                'internal_obj': internal_league,
                'matches': match_wrappers,  # List of match wrappers,
                'needs_mapping': internal_league is None
            })

        country_wrapper = {
            'external_name': c_name,
            'internal_obj': internal_country,  # The Model Instance
            'leagues': league_wrappers,  # This is now a LIST of dicts, not a raw dict
            'needs_mapping': internal_country is None
        }

        view_data.append(country_wrapper)

    context = {
        'pending_id': pending.id,
        'source': pending.source,
        'scraped_from': pending.scraped_from,
        'view_data': view_data,
        'all_teams': Team.objects.all().select_related('country').order_by('name'),
        'all_leagues': League.objects.all().select_related('country').order_by('name'),
        'all_countries': Country.objects.all().order_by('name'),
    }

    return render(request, 'imports_tab/imports_tab_page.html', context)


@login_required
@require_POST
def save_manual_mappings(request):
    def import_or_update_fixtures_in_db(fixtures):
        pass

    try:
        data = json.loads(request.body)

        # --- DEBUG TERMINAL PRINTS ---
        print("\n" + "🚀" * 15)
        print("📥 DATA RECEIVED SUCCESSFULLY")
        print(f"🌍 Countries: {len(data.get('countries', []))}")
        print(f"🏆 Leagues:   {len(data.get('leagues', []))}")
        print(f"⚽ Teams:     {len(data.get('teams', []))}")
        print(f"⚽ Fixtures:  {len(data.get('fixtures', []))}")

        print(data['countries'])
        print(data['leagues'])
        print(data['teams'])
        print(data['fixtures'])
        # for fixture in data.get('fixtures', []):
        #     print(fixture)
        #
        # print("🚀" * 15 + "\n")

        country_type = ContentType.objects.get_for_model(Country)
        league_type = ContentType.objects.get_for_model(League)
        team_type = ContentType.objects.get_for_model(Team)

        updated_counts = {"countries": 0, "leagues": 0, "teams": 0}

        # 1. Extract all country contexts to pre-fetch them in ONE query
        country_names = set()
        for key in ['leagues', 'teams']:
            for item in data.get(key, []):
                if item.get('internal_id') and item.get('country_context'):
                    country_names.add(item['country_context'])

        # Pre-fetch all relevant country mappings into an in-memory dictionary
        # Key: external_name, Value: Country object
        country_mappings_dict = {}
        if country_names:
            country_mappings = ExternalMapping.objects.filter(
                external_name__in=country_names,
                content_type=country_type
            ).select_related('content_type')  # uses generic relation helper

            for mapping in country_mappings:
                country_mappings_dict[mapping.external_name] = mapping.internal_object

        updated_counts = {"countries": 0, "leagues": 0, "teams": 0}

        # Wrap database operations in a single atomic transaction
        with transaction.atomic():

            # 2. Process Countries
            for item in data.get('countries', []):

                internal_id = item.get('internal_id')
                if not internal_id:
                    continue

                ExternalMapping.objects.update_or_create(
                    external_name=item['external_name'],
                    content_type=country_type,
                    defaults={'object_id': internal_id}
                )
                updated_counts["countries"] += 1

            # 3. Process Leagues (0 database hits for country lookups!)
            for item in data.get('leagues', []):

                internal_id = item.get('internal_id')
                if not internal_id:
                    continue

                # Retrieve from in-memory dictionary
                internal_country = country_mappings_dict.get(item.get('country_context'))

                ExternalMapping.objects.update_or_create(
                    external_name=item['external_name'],
                    content_type=league_type,
                    country=internal_country,
                    defaults={'object_id': internal_id}
                )
                updated_counts["leagues"] += 1

            # 4. Process Teams (0 database hits for country lookups!)
            for item in data.get('teams', []):

                internal_id = item.get('internal_id')
                internal_league_name = item.get('internal_league_name')

                if not internal_id:
                    continue

                # Retrieve from in-memory dictionary
                internal_country = country_mappings_dict.get(item.get('country_context'))

                # case where frendlies are played the come with league "Friendlies Clubs"
                # and country "World" i dont want them writen in the DB
                if internal_league_name == "Friendlies Clubs":
                    continue

                ExternalMapping.objects.update_or_create(
                    external_name=item['external_name'],
                    content_type=team_type,
                    country=internal_country,
                    defaults={'object_id': internal_id}
                )
                updated_counts["teams"] += 1

            # process fixtures
            for raw_fixture in data.get('fixtures', []):
                fixture = FixtureService.prepare_scraped_data_to_db_fixture_format(raw_fixture)

                # SAFEGUARD: Skip this row entirely if the data preparation returned None
                if fixture is None:
                    print(f"⚠️ Skipping a raw fixture row because preparation returned None. Raw data: {raw_fixture}")
                    continue

                FixtureService().create_or_update_fixture_in_db(fixture, source_name="OddsPortal")

        return toast_response(
            message=(
                f"Saved mappings:\n"
                f"{updated_counts['countries']} countries,\n"
                f"{updated_counts['leagues']} leagues,\n"
                f"{updated_counts['teams']} teams."
            ),
            level="success"
        )

    except Exception as e:
        print(f"❌ DATABASE PROCESSING ERROR: {str(e)}")
        return toast_response(message=f"Error saving mappings: {str(e)}", level="error", status_code=400)


@login_required
def leagues_list_partial(request):
    """Returns ONLY the table rows. Clean and simple."""
    # We ignore 'q' because Alpine.js handles filtering on the frontend
    leagues = League.objects.select_related('country').all().order_by('name')

    return render(request, 'leagues_tab/leagues_list_partial.html', {'leagues': leagues})


@login_required
def search_external_leagues(request):
    try:

        # 1. Get the raw list from the API
        api_data = LeagueService.search_external_leagues()

        # 2. SORT THE LIST for the HTML
        # This ensures 1, 2, 3... order in your {% for %} loop
        api_data.sort(key=lambda x: x['league']['id'])

        # 3. CREATE THE DICTIONARY for the Session
        # This allows the 'Save' view to find the item instantly by ID
        search_results_dict = {str(item['league']['id']): item for item in api_data}
        request.session['external_search_results'] = search_results_dict

        # 4. PASS THE SORTED LIST to the template
        return render(request, 'leagues_tab/external_leagues_list.html', {
            'api_data': api_data  # The template uses the list
        })
    except Exception as e:
        return HttpResponse(f"<div style='color:red;'>API Error: {str(e)}</div>")


@login_required
@transaction.atomic
def change_league_used_or_not(request):
    selected_ids = request.POST.getlist('league_ids')

    print(selected_ids)

    # Guard clause: if list is empty, just return the partial
    if not selected_ids:
        return leagues_list_partial(request)

    # Use select_for_update() if you expect multiple admins
    # to be clicking this at the exact same time
    leagues = League.objects.filter(id__in=selected_ids).select_for_update()

    for league in leagues:
        league.is_used = not league.is_used
        league.save()

    # Inside the view after the loop
    count = len(selected_ids)
    response = leagues_list_partial(request)
    response["HX-Trigger"] = json.dumps({
        "showToast": {
            "text": f"Successfully toggled {count} leagues.",
            "level": "success"
        }
    })
    return response


@login_required
@require_POST
@transaction.atomic
def save_league_from_api(request):
    league_id = request.POST.get('league_id')
    search_results = request.session.get('external_search_results', {})
    item = search_results.get(str(league_id))

    if not item:
        return HttpResponse("Data expired.", status=400)

    league_data = item.get('league', {})
    country_data = item.get('country', {})
    seasons = item.get('seasons', [])
    current_season = next((s for s in seasons if s.get('current') is True), {})

    # 1. Handle Country & Flag
    country, _ = Country.objects.get_or_create(name=country_data.get('name'))
    if not country.flag:
        LeagueService.download_image_to_field(country_data.get('flag'), country.flag)
        country.save()

    # 2. Prepare Season Data
    today = date.today()
    start_str = current_season.get('start')
    end_str = current_season.get('end')
    start_date = datetime.strptime(start_str, "%Y-%m-%d").date()
    end_date = datetime.strptime(end_str, "%Y-%m-%d").date()
    is_actually_in_season = start_date <= today <= end_date

    # 3. Update or Create the League (ONE CALL)
    league, created = League.objects.update_or_create(
        id=league_id,
        defaults={
            'name': league_data.get('name'),
            'country': country,
            'in_season': is_actually_in_season,
            'season_start': start_date,
            'season_end': end_date,
            'season_year': current_season.get('year'),
            'last_updated_date': today
        }
    )

    # 4. Handle Logo separately ONLY if it's missing
    # We do this after the update_or_create so we have a valid instance
    if not league.logo:
        LeagueService.download_image_to_field(league_data.get('logo'), league.logo)
        league.save()

    response = HttpResponse("""
        <div style="background: #d1fae5; color: #065f46; padding: 6px 12px; border-radius: 6px; font-size: 0.75rem; font-weight: 600;">
            ✅ Added
        </div>
    """)
    response['HX-Trigger'] = 'leagueAdded'
    return response


@login_required
@transaction.atomic
def update_recovery_amount(request):
    print(f"POST DATA: {request.POST}")
    if request.method == "POST":
        item_id = request.POST.get("item_id")
        amount_str = request.POST.get("amount")

        try:
            amount_to_add = Decimal(amount_str)
            if amount_to_add <= 0:
                return toast_response("Please enter an amount greater than 0.", "warning", 400)

            with transaction.atomic():
                # 1. Get the ForRecover parent record
                recovery_parent = get_object_or_404(ForRecover, id=item_id)

                # 2. Create the RecoverFixture entry (the audit trail)
                # Note: fixture_id is None here because this is a 'manual_plus' entry
                RecoverFixture.objects.create(
                    for_recover=recovery_parent,
                    team=recovery_parent.team,
                    value=amount_to_add,
                    value_type="manual_plus",
                    fixture_id=None
                )

                # 3. Update the Parent totals
                recovery_parent.plus_used_manual += amount_to_add

                # Logic: Update status if fully recovered
                if recovery_parent.bets_to_recover <= 0:
                    recovery_parent.is_recovered = True
                    recovery_parent.date_recovered = timezone.now()

                recovery_parent.save()

                TrackingValues.add_entry(amount_to_add, "PLUS_USED")

            # 4. Return fresh data to update the UI table
            # You should call your existing helper that formats ForRecover.objects.all()
            updated_data = for_recover.get_recovery_data()

            return toast_response(
                f"Successfully added manual recovery of {amount_to_add}",
                "success",
                data=updated_data
            )

        except Exception as e:

            # This will print the EXACT error and the line number to your console/terminal

            import traceback

            print(traceback.format_exc())

            return toast_response(f"System Error: {str(e)}", "error", 500)

    return toast_response("Invalid Method", "error", 405)


# distribution tab
@login_required
@transaction.atomic
def equalize_in_range(request):
    if request.method != 'POST':
        return toast_response("Method not allowed", level="error", status_code=405)
    try:
        result = TeamService.redistribute_team_bets_by_no_draw_level()

        return toast_response(
            message="Bets redistributed successfully!",
            level="success",
        )

    except ValueError as e:
        # 3. Return the "Calculations are wrong" error (422)
        # This triggers the 'error' level toast in your frontend
        return toast_response(
            message=str(e),
            level="error",
            status_code=422
        )

    except Exception as e:
        # 4. Catch-all for unexpected server crashes (500)
        return toast_response(
            message="A critical server error occurred.",
            level="error",
            status_code=500
        )


@csrf_exempt
def receive_data(request):
    if request.method != 'POST':
        return JsonResponse({"status": "error", "message": "Only POST allowed"}, status=405)

    try:
        data = json.loads(request.body)
        source = data.get('source', 'unknown')
        # In the new structure, matches is a DICT (Country > League > List)
        all_data = data.get('matches', {})

        # 1. Validation Gate
        if not source or not isinstance(all_data, dict):
            print("❌ Validation Failed: Missing source or data is not a nested dictionary.")
            return JsonResponse({
                "status": "error",
                "message": "Invalid structure: 'source' and 'matches' dictionary required."
            }, status=400)

        print("=" * 200)
        print(f"📥 RECEIVING DATA FROM: {source.upper()}")
        print("=" * 200)

        match_count = 0

        # 2. Triple Loop: Country -> League -> Match List
        for country, leagues in all_data.items():
            for league, match_list in leagues.items():

                # Header for each League group
                print(f"\n🌍 {country.upper()} | 🏆 {league.upper()}")
                print("-" * 200)

                for match in match_list:
                    match_count += 1

                    # Extraction
                    date = match.get('date', 'N/A')
                    time = match.get('time', 'N/A')
                    home = match.get('homeTeam', 'N/A')
                    away = match.get('awayTeam', 'N/A')

                    odds = match.get('odds', {})
                    h_odd = odds.get('home', '-')
                    d_odd = odds.get('draw', '-')
                    a_odd = odds.get('away', '-')

                    # Clean Terminal Output
                    print(
                        f"🕒 {time.ljust(8)} | "
                        f"📅 {date.ljust(15)} | "
                        f"🏠 {home.ljust(25)} | "
                        f"🚌 {away.ljust(25)} | "
                        f"Odds: [1: {h_odd.ljust(6)}] [X: {d_odd.ljust(6)}] [2: {a_odd.ljust(6)}]"
                    )

        print("\n" + "=" * 200)
        print(f"✅ Finished! Processed {match_count} matches.")
        print("=" * 200)

        # 3. Save to Waiting Room (PendingImport)
        # Assuming PendingImport is your model for raw data
        PendingImport.objects.create(
            data=data,
            scraped_from=source
        )

        return JsonResponse({
            "status": "success",
            "message": f"Successfully processed {match_count} matches from {source}"
        }, status=200)

    except json.JSONDecodeError:
        return JsonResponse({"status": "error", "message": "Invalid JSON format"}, status=400)
    except Exception as e:
        # This prints the EXACT line number and file where it crashed in your terminal
        print("🔥 --- DJANGO SERVER ERROR --- 🔥")
        traceback.print_exc()
        print("-------------------------------")

        # Return a clean message to the extension
        return JsonResponse({
            "status": "error",
            "message": f"Server Logic Error: {str(e)}"
        }, status=500)  # 500 is more accurate for code crashes
