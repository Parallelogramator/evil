# config.py
import os

# --- Аутентификация ---
USERNAME = os.getenv("STREAM_USER", "user")
PASSWORD = os.getenv("STREAM_PASSWORD", "password") # Лучше использовать переменные окружения

# --- Настройки видео ---
FRAME_RATE = 10  # Кадров в секунду
VIDEO_QUALITY = 30 # Качество JPEG (1-100)
MONITOR_NUM = 1 # 0=все, 1=основной, 2=второй и т.д.

# --- Настройки аудио ---
# Укажите ТОЧНОЕ имя loopback устройства или None для устройства по умолчанию
# Примеры: 'CABLE Output (VB-Audio Virtual Cable)', 'Monitor of MyVirtualSink', 'BlackHole 2ch'

SAMPLE_RATE = 16000 # Whisper предпочитает 16kHz
CHANNELS = 1
# Длительность куска аудио для обработки Whisper (в секундах)
# Меньше = ниже задержка, но может быть менее точно; Больше = наоборот
BLOCK_DURATION_SECONDS = 4

# --- Настройки Whisper через OpenVINO/Optimum ---
# Модели: "openai/whisper-tiny", "openai/whisper-base", "openai/whisper-small", "medium", "large-v3"
WHISPER_MODEL_ID = "openai/whisper-small" # tiny/base - самые быстрые

# Целевое устройство для OpenVINO: "CPU", "GPU" (для интегрированной графики Intel)
# NPU убрали из явного указания, но если драйверы и OpenVINO поддерживают,
# он может быть выбран автоматически через "AUTO" или использован GPU.
# Указываем CPU для максимальной совместимости или GPU, если есть iGPU Intel.
OV_DEVICE = "CPU"

# Папка для кеширования скачанных моделей и сконвертированных OpenVINO IR файлов
OV_CACHE_DIR = "ov_cache"

# Язык для распознавания (None для автодетекции, "ru", "en", etc.)
ASR_LANGUAGE = "en"

# Параметры VAD (Voice Activity Detection) для фильтрации тишины
# Помогает уменьшить обработку пустых кусков
USE_VAD_FILTER = True
VAD_MIN_SILENCE_DURATION_MS = 400 # Минимальная длительность тишины для VAD


AUDIO_QUEUE_MAXSIZE = 100       # Макс. размер очереди аудио чанков (0 - безлимитно)
AUDIO_CHUNK_DURATION_S = 0.2    # Длительность одного аудио чанка в секундах (влияет на задержку)
MIN_ASR_CHUNK_DURATION_S = 3.0  # Минимальная длительность накопленного аудио для отправки в ASR (секунды)
ASR_SILENCE_THRESHOLD_S = 1.0   # Секунд тишины для принудительной обработки буфера ASR
AUDIO_DEVICE_NAME = None
# --- Настройки сервера ---
HOST = "192.168.0.12"
PORT = 8000