"""
URL configuration for Server project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
import math

import requests
from axes.models import AccessAttempt
from django.contrib import admin
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import path, include
from django.conf import settings
from django.utils import timezone
from django.contrib.auth import views as auth_views
from axes.helpers import get_lockout_response, get_client_ip_address
from axes.utils import reset
from core import views  # Only for the root redirect

from django.conf.urls.static import static

from core import views


# 1. The modern Bouncer
def protected_login(request):
    # 1. Check for Axes Lockout first
    ip = get_client_ip_address(request)
    attempt = AccessAttempt.objects.filter(ip_address=ip).order_by('-attempt_time').first()

    # 1. Check: Is there even a record, and are they at/over the limit?
    if attempt and attempt.failures_since_start >= settings.AXES_FAILURE_LIMIT:

        # 2. They are at the limit. NOW check the clock.
        lockout_end = attempt.attempt_time + timezone.timedelta(hours=settings.AXES_COOLOFF_TIME)

        if timezone.now() >= lockout_end:
            # Time is up! Wipe the slate clean.
            # reset(ip=ip)
            print(f"DEBUG: Lockout expired for {ip}. Record should be cleared automatically.")
        else:
            # Still in the penalty box.
            return redirect('locked_out')

    if request.method == "POST":
        # 2. Get the Turnstile token from the form
        turnstile_token = request.POST.get('cf-turnstile-response')

        # 3. Verify the token with Cloudflare
        # (Using the Global Test Secret Key)
        val_response = requests.post(
            'https://challenges.cloudflare.com/turnstile/v0/siteverify',
            data={
                'secret': '1x0000000000000000000000000000000AA',
                'response': turnstile_token,
                'remoteip': request.META.get('REMOTE_ADDR')
            }
        )

        val_data = val_response.json()

        if not val_data.get('success'):
            # If the captcha fails, don't even check the password
            return render(request, 'login.html', {'form': auth_views.LoginView().get_form(), 'captcha_error': True})

    # 4. If all good (or it's a GET request), show the login view
    return auth_views.LoginView.as_view(template_name='login.html')(request)


# 2. Simple Lockout View
def lockout_view(request):
    ip = get_client_ip_address(request)
    # Look for the latest failure record for this IP
    attempt = AccessAttempt.objects.filter(ip_address=ip).order_by('-attempt_time').first()

    minutes_left = settings.AXES_COOLOFF_TIME * 60  # Default fallback

    if attempt:
        # Calculate: (Last attempt time + Cooloff) - Current time
        lockout_end = attempt.attempt_time + timezone.timedelta(hours=settings.AXES_COOLOFF_TIME)
        remaining = lockout_end - timezone.now()

        # --- THE RELEASE VALVE ---
        # If time is up (or negative), redirect them to login!
        if remaining.total_seconds() <= 0:
            return redirect('login')

        # Convert to total minutes and round up
        minutes_left = math.ceil(remaining.total_seconds() / 60)

    # Ensure we don't show negative numbers if the clock is slightly off
    minutes_left = max(1, minutes_left)

    return render(request, 'lockout.html', {'minutes_left': minutes_left}, status=429)


urlpatterns = [
    path('locked-out/', lockout_view, name='locked_out'),
    path(f'{settings.ADMIN_URL}/', admin.site.urls),

    # 2. Authentication (Simplified)
    path('accounts/login/', protected_login, name='login'),
    path('accounts/logout/', auth_views.LogoutView.as_view(), name='logout'),

    # path('admin/', admin.site.urls),
    # path("api/", include("core.urls")),  # Include your app's URLs

    # # This includes login, logout, password change, etc.
    # path('accounts/login/', auth_views.LoginView.as_view(), name='login'),
    # path('accounts/logout/', auth_views.LogoutView.as_view(), name='logout'),

    # 3. Include App URLs (The Professional way)
    # We remove the 'api/' prefix here so your dashboard URLs stay clean
    path('', include('core.urls')),

    # # Your new dashboard
    # path('dashboard/', views.dashboard, name='dashboard'),
    # # The partial snippet for HTMX
    # path('partial/fixtures/', views.fixtures_partial, name='fixtures_partial'),
    #
    # # Optional: Make the root URL (/) go straight to dashboard
    # path('', views.dashboard, name='home'),
]
# ONLY ADD THIS AT THE VERY END
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
