"""Data providers: live market data from Yahoo Finance, or bundled demo data."""


class TickerNotFound(Exception):
    """No such asset."""


class NotSupported(Exception):
    """The symbol exists but isn't a stock, fund or cryptocurrency (e.g. an index or future)."""


class ProviderError(Exception):
    """The data source failed; the message is safe to show to users."""
