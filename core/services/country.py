from ..models import Country


class CountryService:

    @staticmethod
    def get_or_create_country(name: str) -> Country:
        """
        Returns an existing country or creates a new one.
        """
        country, _ = Country.objects.update_or_create(
            name=name,
            defaults={}  # you can add more fields if needed later
        )
        return country
