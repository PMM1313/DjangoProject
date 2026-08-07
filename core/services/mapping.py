from typing import Optional, Any

from django.contrib.contenttypes.models import ContentType
from ..models import ExternalMapping, Team, League, Country


def create_mapping(external_name: str, model_class, object_id: int, country_id: Optional[int] = None):
    """
    Creates or updates a mapping for any model class (Team, League, Country, etc.)
    """
    content_type = ContentType.objects.get_for_model(model_class)

    # Pass country_id in the lookup args so unique_together works properly
    mapping, created = ExternalMapping.objects.update_or_create(
        external_name=external_name,
        content_type=content_type,
        country_id=country_id,  # Will be None for Country, or an ID for League/Team
        defaults={'object_id': object_id}
    )
    return mapping

    # Examples
    # Pass the actual Model name (no quotes)
    # create_mapping("Man Utd", Team, 33)
    # create_mapping("EPL", League, 2)
    # create_mapping("UK", Country, 1)


def get_internal_object(
        api_name: str,
        model_class: type,
        country: Optional[Any] = None
    ):
    """
    Retrieves the mapped internal object (League, Team, Country) for a given external API name.
    'country' can be a Country model instance, a country_id integer, or None.
    """
    try:
        model_type = ContentType.objects.get_for_model(model_class)

        # Extract country ID if a model instance was passed
        country_id = country.id if hasattr(country, 'id') else country

        mapping = ExternalMapping.objects.select_related('content_type').get(
            external_name=api_name,
            content_type=model_type,
            country_id=country_id
        )
        return mapping.internal_object

    except (ExternalMapping.DoesNotExist, ExternalMapping.MultipleObjectsReturned):
        return None
