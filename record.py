import soundcard as sc
import soundfile as sf

# Получить список всех микрофонов, включая loopback-устройства
mics = sc.all_microphones(include_loopback=True)

# Вывести имена устройств для выбора правильного
for i, mic in enumerate(mics):
    print(f"{i}: {mic.name}")

# Выберите правильное устройство (замените индекс на тот, который соответствует системному аудиовыходу)
loopback_mic = mics[4]  # Пример: индекс 2 для "Stereo Mix"

# Запись аудио (10 секунд при 16000 Гц)
with loopback_mic.recorder(samplerate=16000) as mic:
    print("Запись началась...")
    data = mic.record(numframes=16000 * 10)
    print("Запись завершена.")

# Сохранение записи в файл
sf.write('recording.wav', data, 16000)
print("Аудио сохранено в recording.wav")