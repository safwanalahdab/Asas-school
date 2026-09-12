from django.test import SimpleTestCase
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from config.pagination import StandardPageNumberPagination


class StandardPageNumberPaginationTests(SimpleTestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.items = list(range(1, 76))

    def paginate(self, query_string=""):
        request = Request(self.factory.get(f"/items/{query_string}"))
        paginator = StandardPageNumberPagination()
        page = paginator.paginate_queryset(self.items, request)
        response = paginator.get_paginated_response(page)
        return page, response

    def test_default_first_page_returns_twenty_items_with_standard_contract(self):
        page, response = self.paginate()

        self.assertEqual(page, list(range(1, 21)))
        self.assertEqual(response.data["count"], len(self.items))
        self.assertIsNotNone(response.data["next"])
        self.assertIsNone(response.data["previous"])
        self.assertEqual(
            list(response.data.keys()),
            ["count", "next", "previous", "results"],
        )

    def test_second_page_returns_next_non_overlapping_items(self):
        first_page, _ = self.paginate()
        second_page, response = self.paginate("?page=2")

        self.assertEqual(second_page, list(range(21, 41)))
        self.assertTrue(set(first_page).isdisjoint(second_page))
        self.assertIsNotNone(response.data["previous"])

    def test_page_size_query_parameter_returns_thirty_items(self):
        page, _ = self.paginate("?page_size=30")

        self.assertEqual(len(page), 30)

    def test_page_size_above_maximum_is_capped_at_fifty(self):
        page, response = self.paginate("?page_size=100")

        self.assertEqual(len(page), 50)
        self.assertEqual(response.data["count"], len(self.items))
        self.assertIsNotNone(response.data["next"])
