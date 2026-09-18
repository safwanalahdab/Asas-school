from django.core.paginator import EmptyPage, Paginator
from rest_framework.exceptions import ValidationError


DEFAULT_PAGE_SIZE = 10
MAX_PAGE_SIZE = 100


def _positive_integer(query_params, name, default, maximum=None):
    raw_value = query_params.get(name, default)
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        value = 0

    if value < 1 or (maximum is not None and value > maximum):
        limit_message = f" ولا تتجاوز {maximum}" if maximum else ""
        raise ValidationError(
            {
                "code": "INVALID_PROFILE_PAGINATION",
                "message": "معاملات صفحات الملف الشامل غير صالحة.",
                name: f"يجب أن تكون القيمة عددًا صحيحًا موجبًا{limit_message}.",
            }
        )
    return value


def paginate_profile_queryset(queryset, query_params, prefix):
    page_number = _positive_integer(query_params, f"{prefix}_page", 1)
    page_size = _positive_integer(
        query_params,
        f"{prefix}_page_size",
        DEFAULT_PAGE_SIZE,
        MAX_PAGE_SIZE,
    )
    paginator = Paginator(queryset, page_size)

    try:
        page = paginator.page(page_number)
    except EmptyPage as exc:
        raise ValidationError(
            {
                "code": "INVALID_PROFILE_PAGINATION",
                "message": "معاملات صفحات الملف الشامل غير صالحة.",
                f"{prefix}_page": "رقم الصفحة خارج النطاق المتاح.",
            }
        ) from exc

    return {
        "count": paginator.count,
        "page": page_number,
        "page_size": page_size,
        "total_pages": paginator.num_pages if paginator.count else 0,
        "next": page.next_page_number() if page.has_next() else None,
        "previous": page.previous_page_number() if page.has_previous() else None,
        "results": list(page.object_list),
    }
