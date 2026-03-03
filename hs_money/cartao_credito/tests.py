from django.test import TestCase


class CartaoCreditoSmokeTest(TestCase):
    def test_index(self):
        resp = self.client.get('/cartao/')
        self.assertIn(resp.status_code, (200, 302))
