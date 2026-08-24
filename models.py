"""Legacy compatibility shim aggregating platform models."""

from modules.propostas.models import *  # noqa: F401,F403
from modules.chamados.models import *  # noqa: F401,F403
from extensions import db
