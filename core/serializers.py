from rest_framework import serializers
from .models import Team


class TeamSerializer(serializers.ModelSerializer):
    class Meta:
        model = Team
        fields = '__all__'

    # Validate team_id to ensure uniqueness
    def validate_team_id(self, value):
        if Team.objects.filter(team_id=value).exists():
            raise serializers.ValidationError("Team with this team_id already exists.")
        return value
