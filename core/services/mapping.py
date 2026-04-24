from django.contrib.contenttypes.models import ContentType
from ..models import ExternalMapping, Team, League, Country


def create_mapping(external_name, model_class, object_id):
    """
    Creates or update a mapping for any model class (Team, League, Country, etc.)
    """
    # Django can get the ContentType directly from the class
    content_type = ContentType.objects.get_for_model(model_class)

    # Use update_or_create to prevent duplicate errors
    # if you run the same mapping twice
    mapping, created = ExternalMapping.objects.update_or_create(
        external_name=external_name,
        content_type=content_type,
        defaults={'object_id': object_id}
    )
    return mapping

    # Examples
    # Pass the actual Model name (no quotes)
    # create_mapping("Man Utd", Team, 33)
    # create_mapping("EPL", League, 2)
    # create_mapping("UK", Country, 1)


def get_internal_object(api_name, model_class):
    try:
        model_type = ContentType.objects.get_for_model(model_class)
        mapping = ExternalMapping.objects.get(
            external_name=api_name,
            content_type=model_type
        )
        return mapping.internal_object
    except ExternalMapping.DoesNotExist:
        return None

    # Usage:
    # target_team = get_internal_object("Man Utd", Team)
    # target_league = get_internal_object("EPL", League)
