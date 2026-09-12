from rest_framework import serializers

from .models import StudentHealthProfile


class StudentHealthProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = StudentHealthProfile
        fields = (
            "id",
            "student",
            "blood_type",
            "chronic_diseases",
            "allergies",
            "permanent_medications",
            "special_health_needs",
            "emergency_contact_name",
            "emergency_contact_phone",
            "health_notes",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "student",
            "created_at",
            "updated_at",
        )
