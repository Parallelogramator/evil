# main.py
import asyncio
import logging
import secrets
import sys
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request, Form, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

import config
from streaming import audio, video, asr

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


data = {'status': 'start', 'first_str': '', 'second_str': ''}


security = HTTPBasic()

def get_current_username(credentials: HTTPBasicCredentials = Depends(security)):
    """
    Зависимость для проверки логина и пароля.
    Использует secrets.compare_digest для защиты от атак по времени.
    """
    correct_username = secrets.compare_digest(credentials.username, config.ADMIN_USERNAME)
    correct_password = secrets.compare_digest(credentials.password, config.ADMIN_PASSWORD)
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Lifespan: Starting up...")
    lifespan.background_tasks = set()

    logger.info("Lifespan: Startup complete.")

    yield # Приложение работает здесь

    if hasattr(lifespan, "background_tasks") and lifespan.background_tasks:
        logger.info("Lifespan: Shutting down...")
        # 1. Остановка фоновых задач (осталась только обработка аудио)
        logger.info(f"Cancelling {len(lifespan.background_tasks)} background tasks...")
        tasks_to_cancel = list(lifespan.background_tasks)
        for task in tasks_to_cancel:
            if not task.done():
                task.cancel()
        if tasks_to_cancel:
            await asyncio.gather(*tasks_to_cancel, return_exceptions=True)
        logger.info("Background tasks cancelled.")

    # Убрали остановку аудио захвата
    logger.info("Lifespan: Shutdown complete.")

# --- Создание FastAPI приложения ---
app = FastAPI(title="Screen and Audio Stream Receiver", lifespan=lifespan)

# --- HTTP Эндпоинты ---
app.include_router(video.router) # Включает /ws/source/video и /ws/client/video
app.include_router(audio.router) # Включает /ws/source/audio и /ws/client/audio

@app.get("/", response_class=HTMLResponse)
async def get_index(request: Request, username: str = Depends(get_current_username)):
    logger.info(f"Serving index.html to {request.client.host}")
    return FileResponse("index.html")

@app.get("/status")
async def get_status():
    return {
        "status": "running",
        'status_display': data["status"],
        'first_str': data["first_str"],
        'second_str': data["second_str"],
        "asr_model_loaded": asr.model_loaded,
        "browser_video_clients": len(video.browser_video_clients),
        "browser_audio_clients": len(audio.browser_audio_clients),
    }


@app.post("/update")
async def post_text(first: str = Form(...), second: str = Form(...), status: str = Form('changed'), username: str = Depends(get_current_username)):
    data["status"] = 'changed'
    if first == data['first_str'] and second == data['second_str']:
        data["status"] = 'unchanged'
    if status == 'stopped':
        data["status"] = status
    data['first_str'] = first.rjust(16)
    data['second_str'] = second.rjust(16)
    return 200

@app.get("/text")
async def get_text():
    receive = data.copy()
    data["status"] = 'unchanged'
    return receive


if __name__ == "__main__":
    logger.info(f"Starting server on {config.HOST}:{config.PORT}")
    uvicorn.run(
        "main:app",
        host=config.HOST,
        port=config.PORT,
        log_level="info",
        reload=False
    )