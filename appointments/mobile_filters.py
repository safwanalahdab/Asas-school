from django_filters import rest_framework as filters

from .models import AppointmentRequest


class MobileAppointmentRequestFilter(filters.FilterSet):
    status = filters.ChoiceFilter(choices=AppointmentRequest.Status.choices)

    class Meta:
        model = AppointmentRequest
        fields = ("status",)
