"""riskcheck: a tiny rules-based transaction risk score (practice repo for CI/CD labs)."""

from importlib.metadata import PackageNotFoundError, version

from riskcheck.score import score_transaction

try:
    __version__ = version("riskcheck")      # the installed wheel's version = the VERSION file at build time
except PackageNotFoundError:                # running from a plain checkout, nothing installed
    __version__ = "not installed"

__all__ = ["score_transaction"]
