import json
from django.utils import timezone
from _decimal import InvalidOperation
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.db.models import OuterRef, Exists, Q, Subquery, Max
from django.http import HttpResponseBadRequest, JsonResponse, HttpResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.core.exceptions import ObjectDoesNotExist
# Create your views here.
from django.template.loader import render_to_string
from django.views.decorators.http import require_http_methods, require_POST
from rest_framework.views import APIView

from rest_framework.response import Response
from rest_framework import status, generics

from .forms import ManualFixtureForm, SettleFixtureForm
from .models import Team, Fixture, ForRecover, League, Country, TrackingValue, RecoverFixture
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
@transaction.atomic
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
        service.fetch_and_save_fixtures(date_from, date_to)

        # But we call the static helper directly:
        grouped_data = FixtureService.get_grouped_fixtures()

        html = render_to_string('includes/_fixture_table.html', {
            'grouped_fixtures': grouped_data
        })

        response = HttpResponse(html)
        # We manually add your custom trigger to the HTML response
        # so the toast pops up along with the new table
        response["HX-Trigger"] = json.dumps({
            "showToast": {
                "text": "Fixtures updated successfully!",
                "level": "success"
            }
        })
        return response

    except Exception as e:

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
                season=data['season']
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
    # Find the fixture in your DB
    fixture = get_object_or_404(Fixture, fixture_id=fixture_id)

    if request.method == "POST":
        form = SettleFixtureForm(request.POST)
        if form.is_valid():
            fixture.home_score = form.cleaned_data['home_score']
            fixture.away_score = form.cleaned_data['away_score']
            fixture.status = form.cleaned_data['status']
            fixture.is_played = True if fixture.status == 'Match Finished' else False
            fixture.save()

            # Return success toast and refresh table
            response = toast_response(f"Settled: {fixture.home_team_name} vs {fixture.away_team_name}", level="success")

            # Trigger table refresh
            triggers = json.loads(response["HX-Trigger"])
            triggers["refreshFixtures"] = True
            response["HX-Trigger"] = json.dumps(triggers)
            return response

    # GET request returns the small form partial
    return render(request, 'partials/settle_fixture_form.html', {
        'form': SettleFixtureForm(initial={'status': 'Match Finished'}),
        'fixture': fixture
    })


@login_required  # Ensures only logged-in users can delete
@transaction.atomic  # Ensures the DB stays consistent if deletion is complex
@require_http_methods(["DELETE"])
def delete_fixture(request, pk):
    try:
        fixture = Fixture.objects.get(pk=pk)
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
def play_match(request, pk):
    fixture_obj = get_object_or_404(Fixture, pk=pk)

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
    fixture = FixtureService.play_match(pk, coef)

    html = render_to_string("partials/fixture_row.html", {"f": fixture}, request=request)
    response = HttpResponse(html)
    response['HX-Trigger'] = json.dumps({
        "showToast": {"text": f"Match {fixture.home_team_name} vs {fixture.away_team_name} played!", "level": "success"}
    })
    return response


@login_required  # Ensures only logged-in users can delete
@transaction.atomic  # Ensures the DB stays consistent if deletion is complex
def resolve_match_view(request, pk):
    if request.method == "POST":
        # 1. Execute the business logic (Resetting debts or carrying them over)
        FixtureService.resolve_fixture(pk)

        # 2. Return an empty response with a 200 status.
        # HTMX will see this and, combined with hx-target="closest tr" and hx-swap="delete",
        # it will remove the row from your table.
        return HttpResponse("")


@login_required
@transaction.atomic
def results_and_statuses_view(request):
    # .1 Fetch scores and statuses
    service = FixtureService()
    service.fetch_scores_and_statuses()
    # .2 Get data from DB
    data = service.get_grouped_fixtures()

    # .3 Return data
    return render(request, 'includes/_fixture_table.html', {
        'grouped_fixtures': data
    })


@login_required
def team_fixtures_view(request, team_id):
    # 1. Get the actual team object
    team = get_object_or_404(Team, id=team_id)

    # 2. Pass the team to the template
    # The template will call team.get_fixtures inside the {% with %} tag
    return render(request, 'partials/fixture_list.html', {'team': team})


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
def for_distribution_view(request):
    team_id = request.POST.get("team_id")
    value_str = request.POST.get("for_distribution")

    # 1. Validation
    if not team_id or not value_str:
        return toast_response("Missing required data.", "error", 400)

    try:
        value = Decimal(value_str)
    except (InvalidOperation, TypeError):
        return toast_response("Invalid number format.", "error", 400)

    team = get_object_or_404(Team, id=team_id)

    # 2. Business Logic with Transaction
    try:
        with transaction.atomic():
            # Subtract from Team (handling potential None value)
            current_bets = team.all_bets or Decimal('0.00')
            team.all_bets = current_bets - value
            team.save()

            # Create the Recovery Record
            ForRecover.objects.create(
                team_id=team.id,
                team_name=team.name,
                bets_writen_off=value
            )

            # 3. Success Response
            # Fetch all recovery entries to update the UI
            # We manually build the list to include the 'bets_to_recover' property
            recoveries = ForRecover.objects.all().order_by('-date_added_to_recover')

            data_list = []
            for r in recoveries:
                data_list.append({
                    "id": r.id,
                    "team_name": r.team_name,
                    "bets_writen_off": float(r.bets_writen_off),
                    "bets_recovered": float(r.bets_recovered),
                    "bets_to_recover": float(r.bets_to_recover),
                    "is_recovered": r.is_recovered,
                    "date_added": r.date_added_to_recover.strftime("%Y-%m-%d %H:%M"),  # Match 'date_added'
                    "fixtures_played": 0,  # Add this if you track it, or it will be undefined
                })

            return toast_response(
                f"Created entry for {team.name} successfully!",
                "success",
                200,
                data=data_list
            )

    except Exception as e:
        # Fallback for database errors
        return toast_response(f"Database error: {str(e)}", "error", 500)


def toast_response(message, level="success", status_code=200, data=None):
    """
    Helper to return a JsonResponse with HTMX toast triggers.
    Levels: 'success', 'error', 'info', 'warning'
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
def leagues_list_partial(request):
    """Returns ONLY the table rows. Used for search or refreshes."""
    query = request.GET.get('q', '')

    # Filter leagues by name if search query exists
    leagues = League.objects.select_related('country').filter(
        name__icontains=query
    ).order_by('name')

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
@require_POST
@transaction.atomic
def save_league_from_api(request):
    league_id = request.POST.get('league_id')

    # 1. Pull the results dictionary from the session
    search_results = request.session.get('external_search_results', {})

    # 2. Get the "Whole Item" using the ID
    item = search_results.get(str(league_id))

    if not item:
        return HttpResponse("Data expired. Please search again.", status=400)

    #### LEAGUE NAD COUNTRY LOGO AND FLAG
    league_data = item.get('league', {})
    country_data = item.get('country', {})
    # 1. Handle Country & Flag
    country, created_c = Country.objects.get_or_create(name=country_data.get('name'))
    if created_c or not country.flag:
        LeagueService.download_image_to_field(country_data.get('flag'), country.flag)
        country.save()

    # 2. Handle League & Logo
    league, created_l = League.objects.get_or_create(
        id=league_id,
        defaults={'name': league_data.get('name'), 'country': country}
    )

    # Always update the logo if it's missing
    if not league.logo:
        LeagueService.download_image_to_field(league_data.get('logo'), league.logo)

    league.save()
    #####################################

    # 2. Grab the specific 'current' season directly
    # This looks for the first (and only) dictionary where 'current' is True
    seasons = item.get('seasons', [])
    current_season = next((s for s in seasons if s.get('current') is True), {})

    # 3. Calculate if "Today" is within the season dates
    today = date.today()
    start_str = current_season.get('start')
    end_str = current_season.get('end')

    # Convert date string to a date object
    start_date = datetime.strptime(start_str, "%Y-%m-%d").date()
    end_date = datetime.strptime(end_str, "%Y-%m-%d").date()

    # Check if today falls between start and end (inclusive)
    is_actually_in_season = start_date <= today <= end_date

    # 3. Update or Create the League
    # Note: We use .get() to avoid KeyErrors if a field is missing
    league, created = League.objects.update_or_create(
        id=league_id,
        defaults={
            'name': item.get('league', {}).get('name'),
            'country': Country.objects.get_or_create(name=item.get('country', {}).get('name'))[0],

            # Map API data to your model fields
            'in_season': is_actually_in_season,
            'season_start': current_season.get('start'),
            'season_end': current_season.get('end'),
            'season_year': current_season.get('year'),
            'last_updated_date': date.today()
        }
    )

    response = HttpResponse("""
            <div style="background: #d1fae5; color: #065f46; padding: 6px 12px; border-radius: 6px; font-size: 0.75rem; font-weight: 600;">
                ✅ Added
            </div>
        """)
    # This tells the browser to fire a 'leagueAdded' event
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
