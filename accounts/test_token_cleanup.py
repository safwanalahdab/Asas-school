from datetime import timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)
from rest_framework_simplejwt.tokens import RefreshToken


User = get_user_model()


class FlushExpiredTokensTests(TestCase):
    """SimpleJWT's flushexpiredtokens, as the cleanup timer runs it."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="token-cleanup-user", password="x",
            role=User.Role.SCHOOL_ADMIN, must_change_password=False,
        )

    def token(self, *, expired, blacklisted):
        refresh = RefreshToken.for_user(self.user)
        outstanding = OutstandingToken.objects.get(jti=refresh["jti"])
        if blacklisted:
            refresh.blacklist()
        if expired:
            OutstandingToken.objects.filter(pk=outstanding.pk).update(
                expires_at=timezone.now() - timedelta(minutes=1),
            )
        return outstanding

    def test_flush_deletes_expired_tokens_with_their_blacklist_rows_only(self):
        expired_blacklisted = self.token(expired=True, blacklisted=True)
        self.token(expired=True, blacklisted=False)
        valid = self.token(expired=False, blacklisted=False)
        valid_blacklisted = self.token(expired=False, blacklisted=True)
        self.assertTrue(
            BlacklistedToken.objects.filter(token=expired_blacklisted).exists()
        )

        call_command("flushexpiredtokens", stdout=StringIO())

        self.assertEqual(
            set(OutstandingToken.objects.filter(user=self.user).values_list("pk", flat=True)),
            {valid.pk, valid_blacklisted.pk},
        )
        self.assertEqual(
            list(BlacklistedToken.objects.values_list("token_id", flat=True)),
            [valid_blacklisted.pk],
        )
