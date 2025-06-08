# streaming/video.py
import asyncio
import base64
import logging
import secrets
from typing import List, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, status

import config


logger = logging.getLogger(__name__)
router = APIRouter()

# --- Глобальные переменные ---
# Клиенты, подключенные из браузера
browser_video_clients: List[WebSocket] = []
# Последний полученный кадр (уже как Data URL для простоты)
latest_video_frame_data_url: Optional[str] = None
# Блокировка для доступа к latest_video_frame_data_url
frame_lock = asyncio.Lock()

async def verify_ws_token(websocket: WebSocket):
    """
    Зависимость для проверки токена аутентификации в заголовках WebSocket.
    """
    token = websocket.headers.get("x-auth-token")
    if not token:
        logger.warning(f"WS connection from {websocket.client} rejected: Missing X-Auth-Token header.")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # Используем secrets.compare_digest для защиты от атак по времени
    if not secrets.compare_digest(token, config.WEBSOCKET_SECRET_KEY):
        logger.warning(f"WS connection from {websocket.client} rejected: Invalid X-Auth-Token.")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # Если токен верный, функция просто завершается, и FastAPI продолжает обработку
    logger.info(f"WS connection from {websocket.client} authenticated successfully.")


# --- WebSocket для приема данных от Источника ---
@router.websocket("/ws/source/video")
async def websocket_source_video_endpoint(websocket: WebSocket, dependencies=[Depends(verify_ws_token)]):
    """Принимает сырые JPEG байты от источника."""
    global latest_video_frame_data_url
    await websocket.accept()
    logger.info(f"Video Source connected: {websocket.client}")
    try:
        while True:
            jpeg_bytes = await websocket.receive_bytes()
            if jpeg_bytes:
                # Преобразуем в Data URL сразу при получении
                base64_frame = base64.b64encode(jpeg_bytes).decode("utf-8")
                data_url = f"data:image/jpeg;base64,{base64_frame}"
                async with frame_lock:
                    latest_video_frame_data_url = data_url
                # logger.debug(f"Received video frame: {len(jpeg_bytes)} bytes")

                # Рассылаем кадр браузерам немедленно (альтернатива - фоновая задача)
                if browser_video_clients:
                    # Создаем копию списка для безопасной итерации
                    current_clients = list(browser_video_clients)
                    tasks = [client.send_text(data_url) for client in current_clients]
                    # Не ждем слишком долго, чтобы не блокировать прием следующего кадра
                    await asyncio.wait(tasks, timeout=0.1, return_when=asyncio.ALL_COMPLETED)

    except WebSocketDisconnect:
        logger.info(f"Video Source disconnected: {websocket.client}")
    except Exception as e:
        logger.error(f"Error in source video websocket {websocket.client}: {e}", exc_info=True)
    finally:
        logger.info(f"Video Source connection closed: {websocket.client}")
        # Можно очистить кадр при отсоединении источника?
        # async with frame_lock:
        #     latest_video_frame_data_url = None


# --- WebSocket для отправки данных в Браузер ---
@router.websocket("/ws/client/video")
async def websocket_client_video_endpoint(websocket: WebSocket):
    """Отправляет последний кадр в браузер клиента."""
    await websocket.accept()
    logger.info(f"Browser Video client connected: {websocket.client}")
    if websocket not in browser_video_clients:
        browser_video_clients.append(websocket)

    # Отправляем текущий кадр сразу при подключении, если он есть
    async with frame_lock:
        current_frame = latest_video_frame_data_url
    if current_frame:
        try:
            await websocket.send_text(current_frame)
        except Exception:
            pass # Игнорируем ошибку при первой отправке

    try:
        while True:
            # Просто держим соединение. Отправка идет из /ws/source/video
            # Можно добавить отправку по таймеру, если /ws/source/video не отправляет напрямую
            await websocket.receive_text() # Ждем закрытия или сообщения от клиента
    except WebSocketDisconnect:
        logger.info(f"Browser Video client disconnected: {websocket.client}")
    except Exception as e:
         if "1000 (OK)" not in str(e) and "1001 (going away)" not in str(e):
            logger.error(f"Error in client video websocket {websocket.client}: {e}", exc_info=True)
    finally:
        if websocket in browser_video_clients:
            browser_video_clients.remove(websocket)
            logger.info(f"Browser Video client removed: {websocket.client}")

