"""
Pacote SEI-Anonimizer para anonimização de documentos públicos e textos para LLM/RAG.
"""

from .texto import AnonimizadorTexto
from .main import DocumentAnonimizer, iniciar_interface_grafica, __version__

__all__ = [
    "AnonimizadorTexto",
    "DocumentAnonimizer",
    "iniciar_interface_grafica",
    "__version__"
]