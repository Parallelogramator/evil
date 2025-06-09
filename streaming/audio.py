# streaming/audio.py
import asyncio
import logging
import secrets
from typing import List

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, status

import config
# Импортируем наш новый модуль ASR
import streaming.asr as asr

logger = logging.getLogger(__name__)
router = APIRouter()

# --- Глобальные переменные ---
# Список клиентов-браузеров, ожидающих текст.
# Этот список остается, так как нам все еще нужно знать, кому отправлять результат.
text_recipient_clients: List[WebSocket] = []
text_recipient_clients_lock = asyncio.Lock() # Добавляем лок для безопасности

# --- Удаленные переменные ---
# audio_buffer = np.array([], dtype=np.float32)
# audio_buffer_lock = asyncio.Lock()


async def verify_ws_token(websocket: WebSocket):
    """
    Зависимость для проверки токена аутентификации. Остается без изменений.
    """
    token = websocket.headers.get("x-auth-token")
    if not token:
        logger.warning(f"WS connection from {websocket.client} rejected: Missing X-Auth-Token header.")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    if not secrets.compare_digest(token, config.WEBSOCKET_SECRET_KEY):
        logger.warning(f"WS connection from {websocket.client} rejected: Invalid X-Auth-Token.")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    logger.info(f"WS connection from {websocket.client} authenticated successfully.")


async def broadcast_transcription(text: str, is_final: bool):
    """
    Callback-функция, которую будет вызывать AssemblyAI.
    Она рассылает распознанный текст всем подключенным браузерам.
    """
    async with text_recipient_clients_lock:
        if text_recipient_clients:
            logger.info(f"Broadcasting to {len(text_recipient_clients)} clients: '{text}' (Final: {is_final})")
            payload = {"text": text, "is_final": is_final}
            # Собираем задачи для параллельной отправки
            tasks = [client.send_json(payload) for client in text_recipient_clients]
            # Выполняем отправку и логируем возможные ошибки
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result, client in zip(results, text_recipient_clients):
                if isinstance(result, Exception):
                    logger.warning(f"Failed to send message to client {client.client}: {result}")


# --- WebSocket для приема аудио от Источника ---
@router.websocket("/ws/source/audio")
async def websocket_source_audio_endpoint(websocket: WebSocket, dependencies=[Depends(verify_ws_token)]):
    """
    Принимает сырые аудио байты (16-bit PCM) от источника,
    управляет сессией с AssemblyAI и инициирует рассылку текста.
    """
    await websocket.accept()
    logger.info(f"Authenticated Audio Source connected: {websocket.client}. Starting ASR session.")
    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.error("Could not get running event loop. Cannot start ASR session.")
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR, reason="Server-side event loop error")
        return
    # 1. Инициализируем ASR клиент с нашей callback-функцией для рассылки
    if not asr.init_asr_client(callback=broadcast_transcription, loop=current_loop):
        logger.error("Failed to initialize ASR client for source session.")
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR, reason="ASR service unavailable")
        return

    try:
        # 2. Начинаем сессию стриминга в AssemblyAI
        asr.start_streaming_session()

        # 3. Цикл получения аудио и отправки в AssemblyAI
        while True:
            audio_bytes = await websocket.receive_bytes()
            if audio_bytes:
                # --------------------------------------------------------------------------
                # ВАЖНО: Убедитесь, что ваш клиент-источник теперь отправляет
                # сырые байты в формате 16-bit PCM, а не float32.
                # Никакой конвертации здесь не происходит.
                # --------------------------------------------------------------------------
                asr.stream_audio_chunk(audio_bytes)

    except WebSocketDisconnect:
        logger.info(f"Authenticated Audio Source disconnected: {websocket.client}")
    except Exception as e:
        logger.error(f"Error in source audio websocket {websocket.client}: {e}", exc_info=True)
    finally:
        # 4. КРИТИЧЕСКИ ВАЖНО: Завершаем сессию при отключении источника
        logger.info(f"Closing ASR session for source: {websocket.client}")
        asr.stop_streaming_session()
        logger.info("Audio Source connection closed and ASR session terminated.")


# --- Функция обработки аудио и отправки текста ---
# async def process_audio_and_stream_text():
# Этот обработчик больше не нужен! Его функциональность теперь
# встроена в `websocket_source_audio_endpoint` и callback `broadcast_transcription`.


# --- WebSocket для отправки текста в Браузер ---
@router.websocket("/ws/client/audio")
async def websocket_client_audio_endpoint(websocket: WebSocket):
    """
    Держит соединение с браузером для отправки текста.
    Эта часть почти не меняется, только использует новый лок.
    """
    await websocket.accept()
    logger.info(f"Browser Audio client connected: {websocket.client}")
    async with text_recipient_clients_lock:
        text_recipient_clients.append(websocket)
    try:
        while True:
            # Просто держим соединение, текст отправляется из broadcast_transcription
            # Ожидаем любое сообщение от клиента, чтобы обнаружить разрыв соединения
            await websocket.receive_text()
    except WebSocketDisconnect:
        logger.info(f"Browser Audio client disconnected: {websocket.client}")
    except Exception as e:
        if "1000 (OK)" not in str(e) and "1001 (going away)" not in str(e):
             logger.error(f"Error in client audio websocket {websocket.client}: {e}", exc_info=True)
    finally:
        async with text_recipient_clients_lock:
            if websocket in text_recipient_clients:
                text_recipient_clients.remove(websocket)
                logger.info(f"Browser Audio client removed: {websocket.client}")