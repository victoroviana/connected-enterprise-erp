"""Legacy import shim for proposal API blueprint."""

from modules.propostas.api import *  # noqa: F401,F403
from modules.propostas.api import _CNPJNotFoundError, _CNPJServiceError, _fetch_cnpj_payload  # noqa: F401
