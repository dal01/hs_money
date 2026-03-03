from django.test import TestCase


class CoreSmokeTest(TestCase):
    def test_index_status(self):
        resp = self.client.get('/')
        self.assertIn(resp.status_code, (200, 302))
