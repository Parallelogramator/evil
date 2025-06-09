# streaming/asr.py
import asyncio
import logging
from typing import Optional, Callable

from assemblyai.streaming.v3 import (
    StreamingClient,
    StreamingClientOptions,
    StreamingError,
    StreamingEvents,
    StreamingParameters,
    TerminationEvent,
    TurnEvent,
)
import config

# Настройка логирования
logger = logging.getLogger(__name__)

# --- Глобальные переменные для управления клиентом ---
client: Optional[StreamingClient] = None
# Callback-функция, которую будет вызывать on_turn для возврата текста в основное приложение
transcription_callback: Optional[Callable[[str, bool], None]] = None

main_event_loop: Optional[asyncio.AbstractEventLoop] = None
client_initialized = False


# ---

# --- Обработчики событий от AssemblyAI ---

def on_turn(client_instance: StreamingClient, event: TurnEvent):
    global main_event_loop # Получаем доступ к глобальной переменной
    transcript = event.transcript
    is_final = event.end_of_turn

    if transcription_callback and transcript and main_event_loop:
        logger.debug(f"ASR Turn: '{transcript}' (Final: {is_final})")
        try:
            # --- ИСПОЛЬЗУЕМ СОХРАНЕННЫЙ ЦИКЛ ---
            asyncio.run_coroutine_threadsafe(
                transcription_callback(transcript, is_final),
                main_event_loop # Передаем сохраненный цикл
            )
        except Exception as e:
            # Убираем проверку на RuntimeError, так как main_event_loop уже проверен
            logger.error(f"Ошибка при вызове callback-функции транскрипции: {e}", exc_info=True)
    elif not main_event_loop:
        logger.error("ASR callback failed: main_event_loop was not set during initialization.")

def on_error(client_instance: StreamingClient, error: StreamingError): # <-- Добавьте и сюда для единообразия
    """Вызывается при ошибке в потоке."""
    logger.error(f"Произошла ошибка в AssemblyAI: {error}")


def on_terminated(client_instance: StreamingClient, event: TerminationEvent): # <-- И сюда
    """Вызывается при завершении сессии."""
    logger.info(
        f"Сессия AssemblyAI завершена. Обработано аудио: {event.audio_duration_seconds} секунд."
    )



# --- Функции управления клиентом (API этого модуля) ---

def init_asr_client(callback: Callable[[str, bool], None], loop: asyncio.AbstractEventLoop):
    """
    Инициализирует клиент AssemblyAI, но не подключается.
    Заменяет вашу старую функцию init_asr_model().

    Args:
        callback: Функция, которая будет вызываться с распознанным текстом.
                  Принимает два аргумента:
                  - text (str): Распознанный текст.
                  - is_final (bool): True, если это конец фразы.
    """
    global client, transcription_callback, client_initialized, main_event_loop

    if client_initialized:
        logger.info("ASR клиент AssemblyAI уже инициализирован.")
        return True

    logger.info("Инициализация клиента AssemblyAI...")

    if not config.ASSEMBLYAI_API_KEY or "YOUR_ASSEMBLYAI_API_KEY" in config.ASSEMBLYAI_API_KEY:
        logger.error("API-ключ AssemblyAI не найден или не изменен в config.py.")
        return False

    # Сохраняем callback-функцию для использования в on_turn
    transcription_callback = callback
    main_event_loop = loop

    try:
        # Создаем экземпляр клиента
        client = StreamingClient(
            StreamingClientOptions(api_key=config.ASSEMBLYAI_API_KEY)
        )

        # Регистрируем наши обработчики событий
        client.on(StreamingEvents.Turn, on_turn)
        client.on(StreamingEvents.Error, on_error)
        client.on(StreamingEvents.Termination, on_terminated)

        logger.info("Клиент AssemblyAI успешно инициализирован.")
        client_initialized = True
        return True

    except Exception as e:
        logger.error(f"Не удалось инициализировать клиент AssemblyAI: {e}", exc_info=True)
        client_initialized = False
        return False


def start_streaming_session():
    """
    Подключается к AssemblyAI и начинает сессию потокового распознавания.
    """
    if not client:
        logger.error("Клиент не инициализирован. Сначала вызовите init_asr_client().")
        return

    logger.info(
        f"Подключение к AssemblyAI с параметрами: sample_rate={config.SAMPLE_RATE}, language={config.ASR_LANGUAGE}")
    try:
        # Подключаемся с параметрами из конфига
        client.connect(
            StreamingParameters(
                sample_rate=config.SAMPLE_RATE,
                language_code=config.ASR_LANGUAGE,
            )
        )
        logger.info("Успешное подключение к AssemblyAI. Сессия стриминга активна.")
    except Exception as e:
        logger.error(f"Ошибка подключения к AssemblyAI: {e}", exc_info=True)


def stream_audio_chunk(audio_chunk: bytes):
    """
    Отправляет фрагмент аудио (в байтах) в AssemblyAI для распознавания.
    Эта функция заменяет ваш старый transcribe_audio.

    Args:
        audio_chunk: Фрагмент аудио в формате "сырых" байтов (raw bytes).
                     Например, данные, полученные из микрофона.
    """
    if not client:
        logger.warning("Попытка отправить аудио, но клиент не подключен.")
        return

    try:
        client.stream(audio_chunk)
    except Exception as e:
        logger.error(f"Ошибка при отправке аудио в AssemblyAI: {e}")


def stop_streaming_session():
    """
    Отключается от AssemblyAI и завершает сессию.
    """
    global client, client_initialized, transcription_callback, main_event_loop
    if not client:
        return

    logger.info("Завершение сессии стриминга AssemblyAI...")
    try:
        client.disconnect(terminate=True)
    except Exception as e:
        logger.error(f"Ошибка при отключении от AssemblyAI: {e}")
    finally:
        # Сбрасываем состояние
        client = None
        client_initialized = False
        transcription_callback = None
        main_event_loop = None
        logger.info("Сессия AssemblyAI остановлена и ресурсы очищены.")


