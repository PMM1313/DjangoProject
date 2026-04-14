from django import forms
from .models import Fixture, Team, League, Country


class ManualFixtureForm(forms.Form):
    home_team = forms.ModelChoiceField(
        queryset=Team.objects.all().order_by('name'),  # Use order_by
        label="Home Team"
    )
    away_team = forms.ModelChoiceField(
        queryset=Team.objects.all().order_by('name'),
        label="Away Team")

    league = forms.ModelChoiceField(
        queryset=League.objects.all().order_by('name'),
        label="Select League",
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    country = forms.ModelChoiceField(
        queryset=Country.objects.all().order_by('name'),
        label="Select Country",
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}))
    start_time = forms.TimeField(widget=forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'}))
    season = forms.IntegerField(initial=2025)


class SettleFixtureForm(forms.Form):
    home_score = forms.IntegerField(min_value=0, widget=forms.NumberInput(attrs={'class': 'form-control'}))
    away_score = forms.IntegerField(min_value=0, widget=forms.NumberInput(attrs={'class': 'form-control'}))
    status = forms.ChoiceField(
        choices=[('Match Finished', 'Match Finished'), ('Postponed', 'Postponed'), ('Cancelled', 'Cancelled')],
        widget=forms.Select(attrs={'class': 'form-control'})
    )
