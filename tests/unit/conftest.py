#!/usr/bin/env python3
"""
Configuración global para pytest
"""

import logging
import shutil
import tempfile
from pathlib import Path

import pytest

# Configurar logging para tests
logging.getLogger().setLevel(logging.WARNING)


@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """Setup global para el entorno de testing"""
    # Crear directorio temporal para tests
    test_dir = Path("test_temp")
    test_dir.mkdir(exist_ok=True)

    yield

    # Cleanup después de los tests
    if test_dir.exists():
        shutil.rmtree(test_dir)


@pytest.fixture
def mock_zulip_client():
    """Mock del cliente Zulip"""
    from unittest.mock import Mock

    client = Mock()
    client.send_message.return_value = {"result": "success"}
    client.get_file_content.return_value = b"1,0\n2,1\n3,0\n"
    client.upload_file.return_value = {"result": "success", "uri": "test_uri"}

    return client


@pytest.fixture(autouse=True)
def suppress_logs(caplog):
    """Suprimir logs durante tests para output más limpio"""
    caplog.set_level(logging.ERROR)
