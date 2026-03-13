"""TradeLocker API Client — JWT auth, prices, orders, positions.

This is the primary broker interface. All broker communication goes through this module.
See skills/builder/SKILL.md for full specification.

Phase 1 deliverable: auth + account + instruments + prices + positions + orders + kill switch.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any, Optional

import httpx
import structlog
import yaml

from core.models import Candle

logger = structlog.get_logger(__name__)


class AuthExpired(Exception):
    pass


class BrokerError(Exception):
    def __init__(self, status: int, detail: str):
        self.status = status
        self.detail = detail
        super().__init__(f"BrokerError({status}): {detail}")


class MaxRetriesExceeded(Exception):
    pass


class TradeLockerClient:
    """Async client for TradeLocker Public API.

    Handles JWT auth, token refresh, and all broker operations.
    Every call is logged, retried on transient errors, and re-authed on 401.
    """

    def __init__(self, config_path: str = "config/broker.yaml"):
        with open(config_path) as f:
            self.config = yaml.safe_load(f)

        self.base_url = os.environ.get("TRADELOCKER_BASE_URL", self.config["broker"]["base_url"])
        self.max_retries = self.config["api"]["max_retries"]
        self.backoff_base = self.config["api"]["retry_backoff_base_seconds"]
        self.timeout = self.config["api"]["timeout_seconds"]

        self._access_token: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._token_expiry: float = 0
        self._client: Optional[httpx.AsyncClient] = None

    # ── Lifecycle ──────────────────────────────────────────────────────────

    async def connect(self) -> None:
        """Initialize HTTP client and authenticate."""
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout,
        )
        await self._authenticate()
        logger.info("tradelocker.connected", base_url=self.base_url)

    async def disconnect(self) -> None:
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
        logger.info("tradelocker.disconnected")

    # ── Auth ───────────────────────────────────────────────────────────────

    async def _authenticate(self) -> None:
        """Authenticate with TradeLocker and obtain JWT tokens."""
        assert self._client is not None

        payload = {
            "email": os.environ.get("TRADELOCKER_EMAIL", ""),
            "password": os.environ.get("TRADELOCKER_PASSWORD", ""),
            "server": os.environ.get("TRADELOCKER_SERVER", ""),
        }

        resp = await self._client.post("/auth/jwt/token", json=payload)
        if resp.status_code != 200:
            raise BrokerError(resp.status_code, f"Auth failed: {resp.text}")

        data = resp.json()
        self._access_token = data["accessToken"]
        self._refresh_token = data["refreshToken"]
        # Assume token valid for 15 minutes, refresh 5 min before expiry
        self._token_expiry = time.time() + 900 - self.config["auth"]["token_refresh_buffer_seconds"]
        logger.info("tradelocker.authenticated")

    async def _ensure_auth(self) -> None:
        """Refresh token if near expiry."""
        if time.time() >= self._token_expiry:
            await self._refresh_auth()

    async def _refresh_auth(self) -> None:
        """Refresh JWT using refresh token."""
        assert self._client is not None

        resp = await self._client.post(
            "/auth/jwt/refresh",
            json={"refreshToken": self._refresh_token},
        )
        if resp.status_code != 200:
            logger.warning("tradelocker.refresh_failed, re-authenticating")
            await self._authenticate()
            return

        data = resp.json()
        self._access_token = data["accessToken"]
        self._refresh_token = data["refreshToken"]
        self._token_expiry = time.time() + 900 - self.config["auth"]["token_refresh_buffer_seconds"]
        logger.info("tradelocker.token_refreshed")

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._access_token}"}

    # ── Resilient Request ──────────────────────────────────────────────────

    async def _request(
        self, method: str, path: str, **kwargs: Any
    ) -> dict[str, Any]:
        """Make a broker API request with retry, re-auth, and backoff."""
        assert self._client is not None

        for attempt in range(self.max_retries):
            await self._ensure_auth()
            try:
                resp = await self._client.request(
                    method, path, headers=self._auth_headers(), **kwargs
                )

                if resp.status_code == 401:
                    logger.warning("tradelocker.auth_expired, re-authenticating", attempt=attempt)
                    await self._authenticate()
                    continue

                if resp.status_code == 429:
                    wait = self.backoff_base * (2 ** attempt)
                    logger.warning("tradelocker.rate_limited", wait=wait, attempt=attempt)
                    await asyncio.sleep(wait)
                    continue

                if resp.status_code >= 500:
                    wait = self.backoff_base * (2 ** attempt)
                    logger.warning("tradelocker.server_error", status=resp.status_code, wait=wait)
                    await asyncio.sleep(wait)
                    continue

                if resp.status_code >= 400:
                    raise BrokerError(resp.status_code, resp.text)

                logger.debug("tradelocker.request_ok", method=method, path=path)
                return resp.json()

            except httpx.TimeoutException:
                wait = self.backoff_base * (2 ** attempt)
                logger.warning("tradelocker.timeout", path=path, attempt=attempt, wait=wait)
                await asyncio.sleep(wait)
            except httpx.NetworkError as e:
                wait = self.backoff_base * (2 ** attempt)
                logger.warning("tradelocker.network_error", error=str(e), attempt=attempt)
                await asyncio.sleep(wait)

        raise MaxRetriesExceeded(f"Failed after {self.max_retries} attempts: {method} {path}")

    # ── Account ────────────────────────────────────────────────────────────

    async def get_account_state(self) -> dict[str, Any]:
        """Fetch account balance, equity, margin info."""
        account_id = os.environ.get("TRADELOCKER_ACCOUNT_ID", "")
        return await self._request("GET", f"/trade/accounts/{account_id}/state")

    # ── Instruments ────────────────────────────────────────────────────────

    async def get_instruments(self) -> list[dict[str, Any]]:
        """Fetch available instruments and their specs."""
        account_id = os.environ.get("TRADELOCKER_ACCOUNT_ID", "")
        data = await self._request("GET", f"/trade/accounts/{account_id}/instruments")
        return data.get("d", {}).get("instruments", [])

    async def get_instrument_config(self, symbol: str) -> Optional[dict[str, Any]]:
        """Get config for a specific instrument by symbol name."""
        instruments = await self.get_instruments()
        for inst in instruments:
            if inst.get("name") == symbol or inst.get("tradableInstrumentId") == symbol:
                return inst
        return None

    # ── Prices & Candles ───────────────────────────────────────────────────

    async def get_current_price(self, instrument_id: int) -> dict[str, Any]:
        """Get current bid/ask for an instrument."""
        data = await self._request("GET", f"/trade/quotes/{instrument_id}")
        return data

    async def get_candles(
        self,
        instrument_id: int,
        timeframe: str = "1m",
        count: int = 500,
    ) -> list[Candle]:
        """Fetch historical OHLCV candles."""
        # TradeLocker uses resolution strings like "1", "5", "15", "60"
        tf_map = {"1m": "1", "5m": "5", "15m": "15", "1h": "60", "4h": "240", "1d": "1D"}
        resolution = tf_map.get(timeframe, "1")

        data = await self._request(
            "GET",
            f"/trade/history/{instrument_id}",
            params={"resolution": resolution, "countBack": count},
        )

        candles = []
        bars = data.get("d", {})
        timestamps = bars.get("t", [])
        opens = bars.get("o", [])
        highs = bars.get("h", [])
        lows = bars.get("l", [])
        closes = bars.get("c", [])
        volumes = bars.get("v", [])

        for i in range(len(timestamps)):
            candles.append(Candle(
                timestamp=timestamps[i],
                open=opens[i],
                high=highs[i],
                low=lows[i],
                close=closes[i],
                volume=volumes[i] if i < len(volumes) else 0,
                timeframe=timeframe,
            ))
        return candles

    # ── Positions ──────────────────────────────────────────────────────────

    async def get_positions(self) -> list[dict[str, Any]]:
        """Fetch all open positions."""
        account_id = os.environ.get("TRADELOCKER_ACCOUNT_ID", "")
        data = await self._request("GET", f"/trade/accounts/{account_id}/positions")
        return data.get("d", {}).get("positions", [])

    async def get_orders(self) -> list[dict[str, Any]]:
        """Fetch all pending orders."""
        account_id = os.environ.get("TRADELOCKER_ACCOUNT_ID", "")
        data = await self._request("GET", f"/trade/accounts/{account_id}/orders")
        return data.get("d", {}).get("orders", [])

    # ── Order Placement ────────────────────────────────────────────────────

    async def place_order(
        self,
        instrument_id: int,
        side: str,  # "buy" or "sell"
        quantity: float,
        order_type: str = "market",
        price: Optional[float] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """Place an order. Defaults to dry_run=True for safety."""
        if dry_run:
            logger.info(
                "tradelocker.dry_run_order",
                instrument_id=instrument_id,
                side=side,
                quantity=quantity,
                order_type=order_type,
                price=price,
            )
            return {"dry_run": True, "would_place": {
                "instrumentId": instrument_id,
                "side": side,
                "quantity": quantity,
                "type": order_type,
            }}

        account_id = os.environ.get("TRADELOCKER_ACCOUNT_ID", "")
        payload: dict[str, Any] = {
            "instrumentId": instrument_id,
            "side": side,
            "quantity": quantity,
            "type": order_type,
        }
        if price is not None:
            payload["price"] = price
        if stop_loss is not None:
            payload["stopLoss"] = stop_loss
        if take_profit is not None:
            payload["takeProfit"] = take_profit

        return await self._request(
            "POST", f"/trade/accounts/{account_id}/orders", json=payload
        )

    async def modify_order(
        self, order_id: str, stop_loss: Optional[float] = None, take_profit: Optional[float] = None
    ) -> dict[str, Any]:
        """Modify an existing order's SL/TP."""
        account_id = os.environ.get("TRADELOCKER_ACCOUNT_ID", "")
        payload: dict[str, Any] = {}
        if stop_loss is not None:
            payload["stopLoss"] = stop_loss
        if take_profit is not None:
            payload["takeProfit"] = take_profit
        return await self._request(
            "PATCH", f"/trade/accounts/{account_id}/orders/{order_id}", json=payload
        )

    async def close_position(self, position_id: str) -> dict[str, Any]:
        """Close a specific position."""
        account_id = os.environ.get("TRADELOCKER_ACCOUNT_ID", "")
        return await self._request(
            "DELETE", f"/trade/accounts/{account_id}/positions/{position_id}"
        )

    # ── Kill Switch ────────────────────────────────────────────────────────

    async def kill_switch(self, reason: str = "manual") -> dict[str, Any]:
        """EMERGENCY: Close all positions and cancel all orders immediately."""
        logger.critical("tradelocker.KILL_SWITCH_ACTIVATED", reason=reason)

        results: dict[str, Any] = {"reason": reason, "positions_closed": [], "orders_cancelled": []}

        try:
            positions = await self.get_positions()
            for pos in positions:
                try:
                    await self.close_position(pos["id"])
                    results["positions_closed"].append(pos["id"])
                except Exception as e:
                    logger.error("kill_switch.close_position_failed", position_id=pos["id"], error=str(e))
        except Exception as e:
            logger.error("kill_switch.get_positions_failed", error=str(e))

        try:
            orders = await self.get_orders()
            for order in orders:
                try:
                    account_id = os.environ.get("TRADELOCKER_ACCOUNT_ID", "")
                    await self._request(
                        "DELETE", f"/trade/accounts/{account_id}/orders/{order['id']}"
                    )
                    results["orders_cancelled"].append(order["id"])
                except Exception as e:
                    logger.error("kill_switch.cancel_order_failed", order_id=order["id"], error=str(e))
        except Exception as e:
            logger.error("kill_switch.get_orders_failed", error=str(e))

        logger.critical("tradelocker.KILL_SWITCH_COMPLETE", results=results)
        return results

    # ── Session Check ──────────────────────────────────────────────────────

    async def check_trading_permitted(self, instrument_id: int) -> bool:
        """Check if trading is currently allowed for this instrument."""
        try:
            config = await self.get_instrument_config(str(instrument_id))
            if config and config.get("tradingStatus") == "TRADING":
                return True
            return False
        except Exception:
            return False
