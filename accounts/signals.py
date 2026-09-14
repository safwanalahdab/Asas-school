from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver

from accounts.services import apply_default_role_permissions


@receiver(post_save, sender=get_user_model())
def apply_role_permission_template_on_user_creation(
    sender,
    instance,
    created,
    **kwargs,
):
    if created and not instance.is_superuser and instance.role:
        apply_default_role_permissions(instance)
