# backend/services/wallet/currency_service.py

from typing import Dict, Tuple, Optional
from decimal import Decimal
import logging
from datetime import datetime, timedelta
from uuid import UUID
import asyncio

logger = logging.getLogger(__name__)

class CurrencyError(Exception):
    """Custom exception for currency-related errors"""
    pass

class CurrencyService:
    """
    Service for handling currency-related operations.

    Main functionalities:
    - Currency conversion
    - Exchange rate retrieval
    - Supported currency validation
    - Amount formatting and precision validation
    """
    
    def __init__(self):
        # Supported currencies (aligned with wallet service)
        self.supported_currencies = {
            "USD", "EUR", "GBP", "JPY", "KRW", "CNY",
            "CAD", "AUD", "HKD", "SGD", "TEST"
        }
        
        # Base exchange rates (USD-based)
        self._base_rates: Dict[str, Decimal] = {
            "USD": Decimal("1.0"),
            "EUR": Decimal("0.92"),
            "GBP": Decimal("0.78"),
            "JPY": Decimal("145.0"),
            "KRW": Decimal("1350.0"),
            "CNY": Decimal("7.2"),
            "CAD": Decimal("1.35"),
            "AUD": Decimal("1.50"),
            "HKD": Decimal("7.8"),
            "SGD": Decimal("1.34"),
            "TEST": Decimal("1.0"),  # Test currency for integration
        }
        
        # Thread-safe rates cache (last update time, rates data)
        self._rates_cache: Tuple[datetime, Dict[str, Dict[str, Decimal]]] = (
            datetime.now(), self._compute_all_rates()
        )
        self._cache_lock = asyncio.Lock()
        
    def _compute_all_rates(self) -> Dict[str, Dict[str, Decimal]]:
        """Compute exchange rates for all currency pairs."""
        rates = {}
        
        for from_currency in self.supported_currencies:
            rates[from_currency] = {}
            from_rate = self._base_rates.get(from_currency, Decimal("1.0"))
            
            for to_currency in self.supported_currencies:
                to_rate = self._base_rates.get(to_currency, Decimal("1.0"))
                # Cross-rate calculation: from -> USD -> to
                rates[from_currency][to_currency] = (to_rate / from_rate).quantize(Decimal('0.0001'))
                
        return rates
        
    async def _get_rates(self) -> Dict[str, Dict[str, Decimal]]:
        """Retrieve exchange rates, refreshing cache if expired."""
        async with self._cache_lock:
            cache_time, rates = self._rates_cache
            
            # Check cache expiration (1 hour)
            if datetime.now() - cache_time > timedelta(hours=1):
                try:
                    # In production, this could call an external API
                    rates = self._compute_all_rates()
                    self._rates_cache = (datetime.now(), rates)
                    logger.info("Currency exchange rates refreshed successfully")
                except Exception as e:
                    logger.error(f"Failed to refresh exchange rates: {e}")
                    raise CurrencyError(f"Unable to refresh exchange rates: {e}")
                    
            return rates
    
    async def force_refresh_rates(self) -> None:
        """Force a refresh of the exchange rates cache."""
        async with self._cache_lock:
            try:
                self._rates_cache = (datetime.now(), self._compute_all_rates())
                logger.info("Exchange rates cache forcibly refreshed")
            except Exception as e:
                logger.error(f"Failed to force refresh exchange rates: {e}")
                raise CurrencyError(f"Unable to force refresh exchange rates: {e}")
    
    async def is_currency_supported(self, currency_code: str) -> bool:
        """Check if a currency code is supported."""
        if not isinstance(currency_code, str):
            logger.warning(f"Invalid currency code type: {type(currency_code)}")
            return False
        return currency_code.upper() in self.supported_currencies
    
    async def get_exchange_rate(self, from_currency: str, to_currency: str) -> Decimal:
        """Retrieve the exchange rate between two currencies."""
        # Validate inputs
        from_currency = from_currency.upper()
        to_currency = to_currency.upper()
        
        if not await self.is_currency_supported(from_currency):
            logger.error(f"Unsupported from_currency: {from_currency}")
            raise CurrencyError(f"Unsupported currency: {from_currency}")
        if not await self.is_currency_supported(to_currency):
            logger.error(f"Unsupported to_currency: {to_currency}")
            raise CurrencyError(f"Unsupported currency: {to_currency}")
            
        # Same currency returns 1.0
        if from_currency == to_currency:
            return Decimal("1.0")
            
        # Retrieve rate
        try:
            rates = await self._get_rates()
            rate = rates[from_currency][to_currency]
            logger.debug(f"Exchange rate {from_currency} -> {to_currency}: {rate}")
            return rate
        except Exception as e:
            logger.error(f"Failed to get exchange rate {from_currency} -> {to_currency}: {e}")
            raise CurrencyError(f"Unable to retrieve exchange rate: {e}")
    
    async def convert_currency(self, amount: Decimal, from_currency: str, to_currency: str) -> Decimal:
        """Convert an amount from one currency to another."""
        # Validate inputs
        if not isinstance(amount, Decimal):
            logger.error(f"Invalid amount type: {type(amount)}")
            raise CurrencyError(f"Amount must be a Decimal, got {type(amount)}")
        if amount < 0:
            logger.error(f"Negative amount provided: {amount}")
            raise CurrencyError("Amount cannot be negative")
            
        from_currency = from_currency.upper()
        to_currency = to_currency.upper()
        
        # Get exchange rate and convert
        try:
            rate = await self.get_exchange_rate(from_currency, to_currency)
            converted_amount = amount * rate
            
            # Apply currency-specific precision
            precision = 0 if to_currency in {"JPY", "KRW"} else 2
            return converted_amount.quantize(Decimal(f"0.{'0' * precision}"))
        except CurrencyError:
            raise
        except Exception as e:
            logger.error(f"Currency conversion failed {from_currency} -> {to_currency}: {e}")
            raise CurrencyError(f"Currency conversion failed: {e}")
    
    async def format_amount(self, amount: Decimal, currency: str) -> str:
        """Format an amount according to currency conventions."""
        if not isinstance(amount, Decimal):
            logger.error(f"Invalid amount type for formatting: {type(amount)}")
            raise CurrencyError(f"Amount must be a Decimal, got {type(amount)}")
            
        currency = currency.upper()
        if not await self.is_currency_supported(currency):
            logger.error(f"Unsupported currency for formatting: {currency}")
            raise CurrencyError(f"Unsupported currency: {currency}")
            
        try:
            if currency == "USD":
                return f"${amount:,.2f}"
            elif currency == "EUR":
                return f"€{amount:,.2f}"
            elif currency == "GBP":
                return f"£{amount:,.2f}"
            elif currency == "JPY":
                return f"¥{int(amount):,}"
            elif currency == "KRW":
                return f"₩{int(amount):,}"
            else:
                return f"{amount:,.2f} {currency}"
        except Exception as e:
            logger.error(f"Failed to format amount {amount} for {currency}: {e}")
            raise CurrencyError(f"Unable to format amount: {e}")
    
    async def validate_amount_precision(self, amount: Decimal, currency: str) -> bool:
        """Validate that an amount adheres to the currency's precision rules."""
        if not isinstance(amount, Decimal):
            logger.warning(f"Invalid amount type for precision validation: {type(amount)}")
            return False
            
        currency = currency.upper()
        if not await self.is_currency_supported(currency):
            logger.warning(f"Unsupported currency for precision validation: {currency}")
            return False
            
        try:
            if currency in {"JPY", "KRW"}:
                # No decimal places allowed
                return amount == amount.quantize(Decimal('1'))
            # Most currencies allow up to 2 decimal places
            return amount == amount.quantize(Decimal('0.01'))
        except Exception as e:
            logger.error(f"Precision validation failed for {amount} {currency}: {e}")
            return False
    
    async def get_wallet_display_balance(self, wallet_id: UUID, balance: Decimal, currency: str) -> str:
        """Convert wallet balance to display format."""
        if not isinstance(wallet_id, UUID):
            logger.error(f"Invalid wallet_id type: {type(wallet_id)}")
            raise CurrencyError(f"Wallet ID must be a UUID, got {type(wallet_id)}")
            
        try:
            formatted_balance = await self.format_amount(balance, currency)
            logger.debug(f"Formatted balance for wallet {wallet_id}: {formatted_balance}")
            return formatted_balance
        except CurrencyError:
            raise66
        except Exception as e:
            logger.error(f"Error formatting wallet {wallet_id} balance: {e}")
            return f"{balance} {currency.upper()}"