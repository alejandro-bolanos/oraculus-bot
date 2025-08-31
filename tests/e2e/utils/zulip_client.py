#!/usr/bin/env python3
"""
Cliente Zulip con soporte para envío y recepción de mensajes con adjuntos.
Permite manejar múltiples sesiones de usuarios sin usar threads.
"""

import json
import mimetypes
import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import requests


@dataclass
class ZulipMessage:
    """Representa un mensaje de Zulip"""
    id: int
    sender_email: str
    sender_full_name: str
    content: str
    timestamp: int
    stream: str = ""
    topic: str = ""
    recipient_type: str = ""
    attachments: list[dict[str, Any]] = None

    def __post_init__(self):
        if self.attachments is None:
            self.attachments = []

class ZulipClient:
    """Cliente para interactuar con la API de Zulip"""

    def __init__(self, server_url: str, email: str, api_key: str):
        """
        Inicializa el cliente Zulip
        Args:
            server_url: URL del servidor Zulip (ej: https://your-org.zulipchat.com)
            email: Email del usuario
            api_key: API key del usuario
        """
        self.server_url = server_url.rstrip('/')
        self.email = email
        self.api_key = api_key
        self.session = requests.Session()
        self.session.auth = (email, api_key)
        self.last_message_id = 0

    def _make_request(self, method: str, endpoint: str, **kwargs) -> dict[str, Any]:
        """Realiza una petición HTTP a la API de Zulip"""
        url = urljoin(self.server_url + '/api/v1/', endpoint.lstrip('/'))

        try:
            response = self.session.request(method, url, **kwargs)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Error en petición HTTP: {e}")
            return {"result": "error", "msg": str(e)}
        except json.JSONDecodeError as e:
            print(f"Error decodificando JSON: {e}")
            return {"result": "error", "msg": "Invalid JSON response"}

    def upload_file(self, file_path: str) -> str | None:
        """
        Sube un archivo al servidor Zulip
        Args:
            file_path: Ruta al archivo a subir
        Returns:
            URL del archivo subido o None si hay error
        """
        if not os.path.exists(file_path):
            print(f"Error: El archivo {file_path} no existe")
            return None

        filename = os.path.basename(file_path)
        mime_type, _ = mimetypes.guess_type(file_path)

        try:
            with open(file_path, 'rb') as file:
                files = {'file': (filename, file, mime_type)}
                response = self._make_request('POST', '/user_uploads', files=files)

                if response.get('result') == 'success':
                    return response.get('uri')
                else:
                    print(f"Error subiendo archivo: {response.get('msg', 'Error desconocido')}")
                    return None

        except Exception as e:
            print(f"Error abriendo archivo {file_path}: {e}")
            return None

    def send_message(self, message_type: str, to: str, content: str,
                    topic: str| None = None, attachments: list[str]| None = None) -> bool:
        """
        Envía un mensaje con posibles adjuntos
        Args:
            message_type: 'stream' o 'private'
            to: Destinatario (nombre del stream o email del usuario)
            content: Contenido del mensaje
            topic: Tópico (requerido para mensajes de stream)
            attachments: Lista de rutas de archivos para adjuntar
        Returns:
            True si el mensaje se envió exitosamente
        """
        # Subir archivos adjuntos si los hay
        uploaded_files = []
        if attachments:
            for file_path in attachments:
                uri = self.upload_file(file_path)
                if uri:
                    uploaded_files.append(uri)
                    filename = os.path.basename(file_path)
                    content += f"\n[{filename}]({self.server_url}{uri})"

        # Preparar datos del mensaje
        data = {
            'type': message_type,
            'to': to,
            'content': content
        }

        if message_type == 'stream' and topic:
            data['topic'] = topic

        response = self._make_request('POST', '/messages', json=data)

        if response.get('result') == 'success':
            print(f"Mensaje enviado exitosamente (ID: {response.get('id', 'N/A')})")
            if uploaded_files:
                print(f"Archivos adjuntos: {len(uploaded_files)}")
            return True
        else:
            print(f"Error enviando mensaje: {response.get('msg', 'Error desconocido')}")
            return False

    def get_messages(self, num_messages: int = 10, anchor: str = "newest") -> list[ZulipMessage]:
        """
        Obtiene mensajes del usuario
        Args:
            num_messages: Número de mensajes a obtener
            anchor: Punto de referencia ('newest', 'oldest' o ID de mensaje)
        Returns:
            Lista de objetos ZulipMessage
        """
        data = {
            'anchor': anchor,
            'num_before': num_messages if anchor == "newest" else 0,
            'num_after': 0 if anchor == "newest" else num_messages,
            'apply_markdown': False
        }

        response = self._make_request('GET', '/messages', params=data)

        if response.get('result') != 'success':
            print(f"Error obteniendo mensajes: {response.get('msg', 'Error desconocido')}")
            return []

        messages = []
        for msg_data in response.get('messages', []):
            # Extraer información de adjuntos si existen
            attachments = []
            content = msg_data.get('content', '')

            # Buscar enlaces de archivos en el contenido del mensaje
            if '/user_uploads/' in content:
                import re
                # Buscar patrones de enlaces de archivos
                pattern = r'\[([^\]]+)\]\(([^)]*\/user_uploads\/[^)]+)\)'
                matches = re.findall(pattern, content)
                for filename, url in matches:
                    attachments.append({
                        'filename': filename,
                        'url': url,
                        'full_url': self.server_url + url if not url.startswith('http') else url
                    })

            message = ZulipMessage(
                id=msg_data.get('id'),
                sender_email=msg_data.get('sender_email'),
                sender_full_name=msg_data.get('sender_full_name'),
                content=content,
                timestamp=msg_data.get('timestamp'),
                stream=msg_data.get('display_recipient', ''),
                topic=msg_data.get('subject', ''),
                recipient_type=msg_data.get('type'),
                attachments=attachments
            )
            messages.append(message)

        return messages

    def download_attachment(self, attachment_url: str, save_path: str = "") -> bool:
        """
        Descarga un archivo adjunto
        Args:
            attachment_url: URL del archivo a descargar
            save_path: Ruta donde guardar el archivo (opcional)
        Returns:
            True si se descargó exitosamente
        """
        try:
            # Si la URL es relativa, construir URL completa
            if not attachment_url.startswith('http'):
                full_url = self.server_url + attachment_url
            else:
                full_url = attachment_url

            response = self.session.get(full_url)
            response.raise_for_status()

            # Determinar nombre del archivo si no se especifica save_path
            if save_path == "":
                filename = attachment_url.split('/')[-1]
                save_path = f"downloads/{filename}"

            # Crear directorio si no existe
            os.makedirs(os.path.dirname(save_path), exist_ok=True)

            with open(save_path, 'wb') as f:
                f.write(response.content)

            print(f"Archivo descargado: {save_path}")
            return True

        except Exception as e:
            print(f"Error descargando archivo: {e}")
            return False

    def get_streams(self) -> list[dict[str, Any]]:
        """Obtiene la lista de streams disponibles"""
        response = self._make_request('GET', '/streams')

        if response.get('result') == 'success':
            return response.get('streams', [])
        else:
            print(f"Error obteniendo streams: {response.get('msg', 'Error desconocido')}")
            return []

if __name__ == "__main__":
    pass
