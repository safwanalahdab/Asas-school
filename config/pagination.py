from rest_framework.pagination import PageNumberPagination


class StandardPageNumberPagination(PageNumberPagination):
    page_size_query_param = "page_size"
    max_page_size = 50

    def get_pagination_meta(self, request):
        return {
            "count": self.page.paginator.count,
            "next": self.get_next_link(),
            "previous": self.get_previous_link(),
            "page": self.page.number,
            "page_size": self.page.paginator.per_page,
            "total_pages": self.page.paginator.num_pages,
        }
