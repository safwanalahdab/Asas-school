from rest_framework.routers import DefaultRouter


from .views import (
    AcademicYearViewSet,
    TermViewSet,
    GradeLevelViewSet,
    SectionViewSet,
    SubjectViewSet,
    GradeSubjectViewSet,
)

router = DefaultRouter()

router.register(
    "academic-years",
    AcademicYearViewSet,
    basename="academic-year",
)

router.register(
    "terms",
    TermViewSet,
    basename="term",
)

router.register(
    "grade-levels",
    GradeLevelViewSet,
    basename="grade-level",
)

router.register(
    "sections",
    SectionViewSet,
    basename="section",
)

router.register(
    "subjects",
    SubjectViewSet,
    basename="subject",
)

router.register(
    "grade-subjects",
    GradeSubjectViewSet,
    basename="grade-subject",
)


urlpatterns = router.urls
