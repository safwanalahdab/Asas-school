from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from academics.models import GradeLevel, SupervisorScope, SupervisorScopeStage


@transaction.atomic
def set_supervisor_scope(*, supervisor, scope_type, stages, actor):
    User = get_user_model()

    if not actor or not actor.is_authenticated or not actor.is_active:
        raise PermissionDenied("غير مصرح لك بتعديل نطاق الموجّه.")
    if not (actor.is_superuser or actor.role == User.Role.SCHOOL_ADMIN):
        raise PermissionDenied("فقط إدارة المدرسة تستطيع تعديل نطاق الموجّه.")

    if scope_type not in SupervisorScope.ScopeType.values:
        raise ValidationError({"scope_type": "نوع نطاق الموجّه غير صالح."})

    stage_values = list(stages or [])
    if len(stage_values) != len(set(stage_values)):
        raise ValidationError({"stages": "لا يجوز تكرار المرحلة ضمن النطاق."})

    invalid_stages = set(stage_values) - set(GradeLevel.Stage.values)
    if invalid_stages:
        raise ValidationError({"stages": "توجد مرحلة غير صالحة ضمن النطاق."})

    if scope_type == SupervisorScope.ScopeType.ALL and stage_values:
        raise ValidationError({"stages": "يجب أن تكون المراحل فارغة للنطاق الشامل."})
    if scope_type == SupervisorScope.ScopeType.SELECTED_STAGES and not stage_values:
        raise ValidationError({"stages": "يجب اختيار مرحلة واحدة على الأقل."})

    locked_supervisor = User.objects.select_for_update().get(pk=supervisor.pk)
    if locked_supervisor.role != User.Role.SUPERVISOR:
        raise ValidationError({"supervisor": "لا يمكن إنشاء نطاق لمستخدم ليس موجّهًا."})

    scope, _ = SupervisorScope.objects.select_for_update().get_or_create(
        supervisor=locked_supervisor,
        defaults={"scope_type": scope_type},
    )
    if scope.scope_type != scope_type:
        scope.scope_type = scope_type
        scope.save(update_fields=["scope_type"])

    scope.stages.all().delete()
    SupervisorScopeStage.objects.bulk_create(
        [
            SupervisorScopeStage(scope=scope, stage=stage)
            for stage in stage_values
        ]
    )
    return scope
