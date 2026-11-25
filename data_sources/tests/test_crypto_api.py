import os
import unittest
from unittest.mock import Mock, patch

from data_sources.crypto_api import (
    CryptoAPIConfigurationError,
    CryptoAPIError,
    CryptoAPIRateLimitError,
    FreeCryptoAPIClient,
)


class CryptoAPITests(unittest.TestCase):
    def setUp(self):
        self.session = Mock()
        self.response = Mock()
        self.response.ok = True
        self.response.status_code = 200
        self.response.headers = {}
        self.response.json.return_value = {
            "status": "success",
            "symbols": [{"symbol": "BTC", "last": "10", "date": "2026-01-01 00:00:00"}],
        }
        self.session.get.return_value = self.response

    def test_uses_bearer_auth_and_validates_symbol_response(self):
        client = FreeCryptoAPIClient(api_key="test-secret", session=self.session)
        records = client.get_data("btc")
        self.assertEqual(records[0]["symbol"], "BTC")
        call = self.session.get.call_args
        self.assertEqual(call.kwargs["headers"]["Authorization"], "Bearer test-secret")
        self.assertEqual(call.kwargs["params"], {"symbol": "BTC"})
        self.assertEqual(call.kwargs["timeout"], (5, 20))

    def test_reads_key_from_environment_and_fails_when_missing(self):
        with patch.dict(os.environ, {"FREECRYPTO_API_KEY": "environment-secret"}):
            client = FreeCryptoAPIClient(session=self.session)
            self.assertEqual(client.get_data("BTC")[0]["symbol"], "BTC")
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(CryptoAPIConfigurationError):
                FreeCryptoAPIClient(session=self.session)

    def test_invalid_or_empty_response_is_rejected(self):
        client = FreeCryptoAPIClient(api_key="secret", session=self.session)
        self.response.json.return_value = {"status": "error", "symbols": []}
        with self.assertRaises(CryptoAPIError):
            client.get_data("BTC")
        self.response.json.return_value = {"status": "success", "symbols": []}
        with self.assertRaises(CryptoAPIError):
            client.get_data("BTC")
        self.response.json.return_value = {"status": "success", "symbols": "bad"}
        with self.assertRaises(CryptoAPIError):
            client.get_data("BTC")

    def test_retries_rate_limit_once_and_stops_after_bounded_attempts(self):
        limited = Mock(status_code=429, headers={"Retry-After": "0"}, ok=False)
        success = self.response
        self.session.get.side_effect = [limited, success]
        sleeper = Mock()
        client = FreeCryptoAPIClient(
            api_key="secret", session=self.session, max_retries=1, sleeper=sleeper
        )
        self.assertEqual(client.get_data("BTC")[0]["symbol"], "BTC")
        self.assertEqual(self.session.get.call_count, 2)
        sleeper.assert_called_once_with(0.0)

        self.session.get.reset_mock()
        self.session.get.side_effect = [limited, limited]
        client = FreeCryptoAPIClient(
            api_key="secret", session=self.session, max_retries=1, sleeper=lambda _: None
        )
        with self.assertRaises(CryptoAPIRateLimitError):
            client.get_data("BTC")
        self.assertEqual(self.session.get.call_count, 2)

    def test_does_not_retry_permanent_http_errors(self):
        denied = Mock(status_code=403, headers={}, ok=False)
        self.session.get.return_value = denied
        client = FreeCryptoAPIClient(api_key="secret", session=self.session)
        with self.assertRaises(CryptoAPIError):
            client.get_data("BTC")
        self.assertEqual(self.session.get.call_count, 1)


if __name__ == "__main__":
    unittest.main()
