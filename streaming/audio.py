# streaming/audio.py
import asyncio
import logging
import time
from typing import List

import numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

import config
import streaming.asr as asr


logger = logging.getLogger(__name__)
router = APIRouter()

# --- Глобальные переменные ---
# Клиенты браузера, ожидающие текст
browser_audio_clients: List[WebSocket] = []
audio_buffer = np.array([], dtype=np.float32)
audio_buffer_lock = asyncio.Lock()
# Убрали audio_stream_obj

# --- WebSocket для приема аудио от Источника ---
@router.websocket("/ws/source/audio")
async def websocket_source_audio_endpoint(websocket: WebSocket):
    """Принимает сырые float32 аудио байты от источника и добавляет в буфер."""
    global audio_buffer
    await websocket.accept()
    logger.info(f"Audio Source connected: {websocket.client}")
    try:
        while True:
            audio_bytes = await websocket.receive_bytes()
            if audio_bytes:
                try:
                    # Преобразуем байты обратно в numpy массив float32
                    # Важно: источник должен слать именно float32
                    new_samples = np.frombuffer(audio_bytes, dtype=np.float32)
                    # Добавляем в буфер асинхронно
                    async with audio_buffer_lock:
                         audio_buffer = np.append(audio_buffer, new_samples)
                    # logger.debug(f"Received audio samples: {len(new_samples)}. Buffer size: {len(audio_buffer)}")
                except Exception as e:
                    logger.error(f"Error processing received audio bytes: {e}")

    except WebSocketDisconnect:
        logger.info(f"Audio Source disconnected: {websocket.client}")
    except Exception as e:
        logger.error(f"Error in source audio websocket {websocket.client}: {e}", exc_info=True)
    finally:
        logger.info(f"Audio Source connection closed: {websocket.client}")
        # Очистить буфер при отсоединении источника?
        # async with audio_buffer_lock:
        #     audio_buffer = np.array([], dtype=np.float32)
        # logger.info("Audio buffer cleared on source disconnect.")


# --- Функция обработки аудио буфера и отправки текста браузерам ---
async def process_audio_and_stream_text():
    """Обрабатывает аудио из буфера и отправляет распознанный текст браузерам."""
    global audio_buffer
    logger.info("Starting audio processing and streaming loop.")
    samples_per_block = int(config.SAMPLE_RATE * config.BLOCK_DURATION_SECONDS)
    last_speech_time = time.time()
    silence_threshold = 5

    while True:
        try:
            block_to_process = None
            async with audio_buffer_lock:
                if len(audio_buffer) >= samples_per_block:
                    block_to_process = audio_buffer[:samples_per_block]
                    audio_buffer = audio_buffer[samples_per_block:]

            if block_to_process is not None and block_to_process.size > 0:
                 loop = asyncio.get_event_loop()
                 full_text = await loop.run_in_executor(
                     None, asr.transcribe_audio, block_to_process
                 )

                 if full_text and full_text != 'you':
                     logger.info(f"Recognized: {full_text}")
                     last_speech_time = time.time()
                     if browser_audio_clients: # Отправляем клиентам браузера
                         # Копируем список для безопасной итерации
                         current_clients = list(browser_audio_clients)
                         tasks = [client.send_text(full_text) for client in current_clients]
                         await asyncio.gather(*tasks, return_exceptions=True)
                 elif time.time() - last_speech_time > silence_threshold:
                     # logger.info("No speech detected in the last block.") # Меньше спама
                     last_speech_time = time.time()

                 await asyncio.sleep(0.05)
            else:
                 await asyncio.sleep(0.1)

        except asyncio.CancelledError:
            logger.info("Audio processing task cancelled.")
            break
        except Exception as e:
            logger.error(f"Error in audio processing loop: {e}", exc_info=True)
            await asyncio.sleep(1)


# --- WebSocket для отправки текста в Браузер ---
@router.websocket("/ws/client/audio")
async def websocket_client_audio_endpoint(websocket: WebSocket):
    """Держит соединение с браузером для отправки текста."""
    await websocket.accept()
    logger.info(f"Browser Audio client connected: {websocket.client}")
    if websocket not in browser_audio_clients:
        browser_audio_clients.append(websocket)
    try:
        while True:
            # Просто держим соединение, текст отправляется из process_audio_and_stream_text
            await websocket.receive_text()
    except WebSocketDisconnect:
        logger.info(f"Browser Audio client disconnected: {websocket.client}")
    except Exception as e:
        if "1000 (OK)" not in str(e) and "1001 (going away)" not in str(e):
             logger.error(f"Error in client audio websocket {websocket.client}: {e}", exc_info=True)
    finally:
        if websocket in browser_audio_clients:
            browser_audio_clients.remove(websocket)
            logger.info(f"Browser Audio client removed: {websocket.client}")