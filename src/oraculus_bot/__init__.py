# src/oraculus_bot/__init__.py

# Importamos las clases y funciones que queremos que sean accesibles
from .oraculus_bot import OraculusBot, create_config_template

# Opcional: define qué se importa con `from oraculus_bot import *`
__all__ = ["OraculusBot", "create_config_template"]

# También puedes poner metadatos
__version__ = "0.1.0"