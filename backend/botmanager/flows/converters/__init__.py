"""Conversão de robôs taskt (.xml) e OpenBots Studio (.obscript/.json, projeto .zip) em fluxos nativos."""
from .readers import read_robot  # noqa: F401
from .translate import ConversionResult, convert  # noqa: F401
