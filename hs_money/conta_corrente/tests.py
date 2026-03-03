from django.test import TestCase


class ContaCorrenteSmokeTest(TestCase):
    def test_index(self):
        resp = self.client.get('/conta/')
        self.assertIn(resp.status_code, (200, 302))
