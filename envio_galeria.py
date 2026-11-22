"""Upload assíncrono de fotos para a galeria Django.

Após salvar a foto local, importe e chame
``enviar_foto_em_segundo_plano(caminho_arquivo, codigo_evento=...)`` nos
fluxos de captura de 1 Foto e Tira 3x do app.py.
"""

import logging
import os
import threading

import requests


logger = logging.getLogger(__name__)
DEFAULT_UPLOAD_URL = "http://127.0.0.1:8000/api/upload/"
DEVELOPMENT_API_KEY = "dev-totem-api-key-change-me"


def _enviar_foto(caminho_arquivo, codigo_evento, upload_url, api_key, timeout):
    try:
        with open(caminho_arquivo, "rb") as imagem:
            response = requests.post(
                upload_url,
                headers={"X-API-KEY": api_key},
                files={"imagem": imagem},
                data={"codigo_evento": codigo_evento},
                timeout=timeout,
            )
        if response.status_code in (200, 201):
            logger.info("Foto enviada para a galeria: %s", caminho_arquivo)
        else:
            logger.error(
                "Falha ao enviar foto para a galeria: HTTP %s (%s)",
                response.status_code,
                caminho_arquivo,
            )
    except requests.RequestException as erro:
        logger.error("Erro de conexão ao enviar foto para a galeria: %s", erro)
    except OSError as erro:
        logger.error("Não foi possível abrir a foto para envio: %s", erro)


def enviar_foto_em_segundo_plano(
    caminho_arquivo,
    codigo_evento="evento_padrao",
    upload_url=DEFAULT_UPLOAD_URL,
    api_key=None,
    timeout=15,
):
    """Inicia o upload em uma thread daemon e a retorna sem aguardar a rede."""
    chave = (
        api_key
        or os.environ.get("TOTEM_API_KEY")
        or DEVELOPMENT_API_KEY
    )
    thread = threading.Thread(
        target=_enviar_foto,
        args=(caminho_arquivo, codigo_evento, upload_url, chave, timeout),
        daemon=True,
    )
    thread.start()
    return thread
