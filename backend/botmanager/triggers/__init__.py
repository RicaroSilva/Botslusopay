"""Métodos de disparo automático.

Cada tipo regista-se em TRIGGER_TYPES com um esquema de configuração e,
opcionalmente, uma função periódica (avaliada pelo scheduler). Adicionar um
novo método = criar um módulo com uma subclasse de TriggerType e registá-la.
"""
from .base import TRIGGER_TYPES, TriggerType, fire_rule, get_trigger_type  # noqa: F401
from . import after_bot, poll_http, schedule, webhook  # noqa: F401,E402
