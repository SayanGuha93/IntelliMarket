"""FreeCryptoAPI client for live market data only."""

from __future__ import annotations

import os
import time
from email.utils import parsedate_to_datetime

import requests

BASE_URL = "https://api.freecryptoapi.com/v1"
DEFAULT_TIMEOUT = (5, 20)
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class CryptoAPIError(RuntimeError):
    """Safe API error that never includes request headers or credentials."""


class CryptoAPIConfigurationError(CryptoAPIError):
    pass


class CryptoAPIRateLimitError(CryptoAPIError):
    pass


class FreeCryptoAPIClient:
    def __init__(
        self,
        api_key=None,
        *,
        session=None,
        timeout=DEFAULT_TIMEOUT,
        max_retries=2,
        sleeper=time.sleep,
        base_url=BASE_URL,
    ):
        self._api_key = api_key or os.getenv("FREECRYPTO_API_KEY")
        if not self._api_key:
            raise CryptoAPIConfigurationError(
                "FREECRYPTO_API_KEY is not set in the process environment."
            )
        if max_retries < 0:
            raise ValueError("max_retries cannot be negative.")
        self._session = session or requests.Session()
        self._timeout = timeout
        self._max_retries = max_retries
        self._sleep = sleeper
        self._base_url = base_url.rstrip("/")

    def get_data(self, symbol):
        """Fetch one symbol only; the previously tested batch syntax was empty."""
        symbol = str(symbol).strip().upper()
        if not symbol:
            raise ValueError("A non-empty symbol is required.")

        payload = self._get("/getData", {"symbol": symbol})
        if not isinstance(payload, dict) or payload.get("status") != "success":
            raise CryptoAPIError(f"FreeCryptoAPI returned an unsuccessful response for {symbol}.")
        records = payload.get("symbols")
        if not isinstance(records, list):
            raise CryptoAPIError(f"FreeCryptoAPI response for {symbol} has no symbols array.")
        matching = [
            record for record in records
            if isinstance(record, dict)
            and str(record.get("symbol", "")).strip().upper() == symbol
        ]
        if not matching:
            raise CryptoAPIError(f"FreeCryptoAPI returned no matching data for {symbol}.")
        return matching

    def _get(self, endpoint, params):
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
        }
        for attempt in range(self._max_retries + 1):
            try:
                response = self._session.get(
                    f"{self._base_url}{endpoint}",
                    params=params,
                    headers=headers,
                    timeout=self._timeout,
                )
            except requests.RequestException as exc:
                if attempt >= self._max_retries:
                    raise CryptoAPIError(
                        f"FreeCryptoAPI request failed ({type(exc).__name__})."
                    ) from None
                self._sleep(min(2 ** attempt, 8))
                continue

            if response.status_code in RETRYABLE_STATUS_CODES:
                if attempt >= self._max_retries:
                    if response.status_code == 429:
                        raise CryptoAPIRateLimitError(
                            "FreeCryptoAPI rate limit persisted after bounded retries."
                        )
                    raise CryptoAPIError(
                        f"FreeCryptoAPI temporary server error ({response.status_code})."
                    )
                delay = self._retry_delay(response, attempt)
                self._sleep(delay)
                continue

            if not response.ok:
                raise CryptoAPIError(
                    f"FreeCryptoAPI returned HTTP {response.status_code}."
                )
            try:
                payload = response.json()
            except ValueError:
                raise CryptoAPIError("FreeCryptoAPI returned invalid JSON.") from None
            if not isinstance(payload, dict):
                raise CryptoAPIError("FreeCryptoAPI returned an invalid response object.")
            return payload

        raise CryptoAPIError("FreeCryptoAPI request exhausted its retry budget.")

    @staticmethod
    def _retry_delay(response, attempt):
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return min(max(float(retry_after), 0.0), 30.0)
            except ValueError:
                try:
                    seconds = (parsedate_to_datetime(retry_after) - parsedate_to_datetime(
                        response.headers.get("Date")
                    )).total_seconds()
                    return min(max(seconds, 0.0), 30.0)
                except (TypeError, ValueError, OverflowError):
                    pass
        return min(2 ** attempt, 8)
