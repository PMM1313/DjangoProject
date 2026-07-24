from ..models import Country


class CountryService:

    @staticmethod
    def get_or_create_country(name: str) -> Country:
        """
        Returns an existing country or creates a new one.
        """
        # Trim leading/trailing whitespace to prevent duplicate errors like "Vietnam " vs "Vietnam"
        clean_name = name.strip() if name else name  # "if name else name" strip wont crash the DB if name is None

        country, created = Country.objects.get_or_create(
            name=clean_name
        )
        return country
