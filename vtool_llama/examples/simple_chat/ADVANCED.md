# VTool Llama Chat Web - Documentación Avanzada

## Arquitectura

### Backend (FastAPI)

```
main.py
├── Inicialización de VToolLlama (instancia global)
├── Endpoints de API
│   ├── GET /api/characters
│   ├── POST /api/load-character
│   ├── POST /api/chat
│   ├── POST /api/chat-stream (SSE)
│   ├── POST /api/reset
│   ├── POST /api/save-episode
│   └── GET /api/memory
└── State Manager (singleton VToolLlama)
```

**Decisiones de Diseño:**

- **Instancia Global**: Una única instancia de `VToolLlama` se mantiene en memoria
  - Evita recargar el modelo constantemente
  - Preserva estado psicológico entre requests
  - Eficiente para GPU/VRAM

- **Streaming con SSE**: Respuestas en tiempo real token por token
  - Mejor UX que esperar respuesta completa
  - Reduce latencia percibida
  - Cliente puede cancelar mid-stream

- **State en Memoria**: Personaje cargado mantiene su contexto
  - Historial de chat persiste
  - Psychology engine activo
  - KV Cache cacheado

### Frontend (Vanilla JS)

```
index.html
├── UI (CSS Grid + Flexbox)
│   ├── Sidebar (personajes)
│   ├── Chat Header
│   ├── Messages Area
│   └── Input Area (textarea + send)
├── JavaScript State
│   ├── currentCharacter
│   ├── characters[]
│   └── isLoading
└── Event Handlers
    ├── Character Selection
    ├── Message Send
    ├── SSE Listener
    └── UI Updates
```

**Decisiones de Diseño:**

- **Sin Framework**: Vanilla JS para máxima compatibilidad y velocidad
- **CSS Variables**: Fácil customización de tema
- **Autoscroll**: Mensajes nuevos siempre visibles
- **Disabled State**: Input deshabilitado durante carga

## Extensiones Posibles

### 1. Base de Datos (Persistencia)

Agregar PostgreSQL/SQLite para guardar:
- Historiales de conversación
- Episodios
- Preferences de usuario

```python
# main.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DATABASE_URL = "sqlite:///./chat.db"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

@app.post("/api/save-chat-history")
async def save_history(character: str, db: Session = Depends(get_db)):
    # Guardar conversación a BD
    pass
```

### 2. Autenticación de Usuarios

Agregar JWT/sesiones para multi-usuario:

```python
from fastapi.security import HTTPBearer

security = HTTPBearer()

@app.post("/api/login")
async def login(username: str, password: str):
    token = create_jwt_token(username)
    return {"access_token": token}

@app.post("/api/chat-stream")
async def chat_stream(
    request: ChatRequest,
    credentials: HTTPAuthCredentials = Depends(security)
):
    user_id = verify_token(credentials.credentials)
    # Chat por usuario
    pass
```

### 3. Múltiples Instancias de LLM

Para soportar múltiples conversaciones paralelas:

```python
from typing import Dict

# Pool de instancias
_llm_pool: Dict[str, VToolLlama] = {}

def get_user_llm(user_id: str) -> VToolLlama:
    if user_id not in _llm_pool:
        _llm_pool[user_id] = VToolLlama(auto_load=True)
    return _llm_pool[user_id]
```

### 4. WebSocket para Multi-usuario

Cambiar de SSE a WebSocket para chats en tiempo real:

```python
from fastapi import WebSocket

@app.websocket("/ws/{character}")
async def websocket_endpoint(websocket: WebSocket, character: str):
    await websocket.accept()
    
    try:
        while True:
            message = await websocket.receive_text()
            
            llm = get_llm()
            for token in llm.stream_chat(message):
                await websocket.send_text(token)
                
    except Exception as e:
        await websocket.send_text(f"[ERROR] {e}")
    finally:
        await websocket.close()
```

### 5. Voice Input/Output

Agregar TTS/STT:

```bash
pip install pyttsx3 speech_recognition
```

```python
import pyttsx3
import speech_recognition as sr

@app.post("/api/chat-voice")
async def chat_voice(audio_file: UploadFile):
    # Transcribir audio → texto
    recognizer = sr.Recognizer()
    # ...
    
    # Obtener respuesta
    response = llm.chat(transcribed_text)
    
    # Text → Speech
    engine = pyttsx3.init()
    engine.save_to_file(response, "output.mp3")
    
    return FileResponse("output.mp3")
```

### 6. Admin Panel

Dashboard para gestionar personajes:

```python
@app.get("/admin/characters/{name}/state")
async def get_character_state_admin(name: str):
    llm = get_llm()
    llm.load_character(name, semantic_memory=True)
    
    return {
        "character": name,
        "psychology": llm.state_manager.psychology_manager.current_state,
        "emotions": llm.state_manager.psychology_manager.emotional_state,
        "memory_count": len(llm.get_memory()),
        "episodes": llm.list_episodes()
    }

@app.post("/admin/characters/{name}/rebuild")
async def rebuild_character(name: str):
    llm = get_llm()
    llm.load_character(name, semantic_memory=True)
    llm.rebuild_personality_state()
    return {"success": True}
```

### 7. Tool Calling

Integrar tools/plugins para que el personaje pueda ejecutar acciones:

```python
@app.post("/api/chat-stream")
async def chat_stream(request: ChatRequest):
    llm = get_llm()
    
    tools = [
        {
            "name": "get_time",
            "description": "Obtiene la hora actual",
            "parameters": {}
        },
        {
            "name": "search_web",
            "description": "Busca en internet",
            "parameters": {"query": "string"}
        }
    ]
    
    # Pasar tools a VToolLlama
    for token in llm.stream_chat(request.message, tools=tools):
        yield f"data: {token}\n\n"
```

### 8. Analytics & Logging

Monitoreo de interacciones:

```python
from datetime import datetime
import json

class ChatLogger:
    def __init__(self, log_file="chats.jsonl"):
        self.log_file = log_file
    
    def log_chat(self, character: str, user_msg: str, ai_response: str):
        entry = {
            "timestamp": datetime.now().isoformat(),
            "character": character,
            "user": user_msg,
            "response": ai_response,
            "tokens": len(ai_response.split())
        }
        with open(self.log_file, "a") as f:
            f.write(json.dumps(entry) + "\n")

logger = ChatLogger()

@app.post("/api/chat-stream")
async def chat_stream(request: ChatRequest):
    # ... chat ...
    logger.log_chat(request.character, request.message, response)
```

### 9. Docker Deployment

Crear Dockerfile para containerizar:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py index.html ./

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

```bash
# Build
docker build -t vtool-llama-chat .

# Run
docker run -p 8000:8000 \
  -v /ruta/a/modelos:/models \
  -v /ruta/a/personajes:/app/personajes \
  --gpus all \
  vtool-llama-chat
```

### 10. Real-time Collaboration

Múltiples usuarios chateando con el mismo personaje:

```python
from fastapi import BackgroundTasks

active_connections: List[WebSocket] = []

@app.websocket("/ws/collaborative/{character}")
async def websocket_collaborative(websocket: WebSocket, character: str):
    await websocket.accept()
    active_connections.append(websocket)
    
    try:
        while True:
            message = await websocket.receive_text()
            
            # Broadcast a todos
            llm = get_llm()
            llm.load_character(character, semantic_memory=True)
            response = llm.chat(message)
            
            for conn in active_connections:
                await conn.send_json({
                    "type": "message",
                    "content": response,
                    "character": character
                })
    finally:
        active_connections.remove(websocket)
```

## Performance Tips

### 1. Caching

```python
from functools import lru_cache

@lru_cache(maxsize=100)
def get_character_info(name: str):
    # Cache de info de personajes
    pass
```

### 2. Async Operations

```python
import asyncio

@app.post("/api/chat-stream")
async def chat_stream(request: ChatRequest):
    # Offload CPU-intensive work
    response = await asyncio.to_thread(
        llm.stream_chat,
        request.message
    )
    # ...
```

### 3. Memory Optimization

```python
# main.py
import psutil
import gc

@app.get("/api/memory-stats")
async def memory_stats():
    process = psutil.Process()
    memory = process.memory_info()
    
    return {
        "rss_mb": memory.rss / 1024 / 1024,
        "vms_mb": memory.vms / 1024 / 1024,
        "percent": process.memory_percent()
    }

# Limpiar periodicamente
@app.post("/api/gc")
async def garbage_collect():
    collected = gc.collect()
    return {"collected_objects": collected}
```

### 4. Connection Pooling

```python
from sqlalchemy.pool import QueuePool

engine = create_engine(
    DATABASE_URL,
    poolclass=QueuePool,
    pool_size=10,
    max_overflow=20
)
```

## Testing

Crear tests para la API:

```python
# test_main.py
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_list_characters():
    response = client.get("/api/characters")
    assert response.status_code == 200
    assert isinstance(response.json(), list)

def test_load_character():
    response = client.post(
        "/api/load-character",
        json={"character": "Ares"}
    )
    assert response.status_code in [200, 404]

def test_health():
    response = client.get("/health")
    assert response.status_code == 200

if __name__ == "__main__":
    pytest.main([__file__])
```

```bash
pip install pytest pytest-asyncio
pytest test_main.py -v
```

## Troubleshooting Avanzado

### 1. Memory Leaks

```python
import tracemalloc

tracemalloc.start()

# ... code ...

current, peak = tracemalloc.get_traced_memory()
print(f"Current: {current / 1024 / 1024}MB; Peak: {peak / 1024 / 1024}MB")
```

### 2. Connection Issues

```python
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("uvicorn")
```

### 3. CUDA OOM

```python
# Reducir contexto
llm.config['n_ctx'] = 2048
llm.reload_model()
```

## Roadmap

- [ ] Multi-user support with auth
- [ ] PostgreSQL persistence
- [ ] WebSocket realtime
- [ ] Voice I/O
- [ ] Admin dashboard
- [ ] Analytics
- [ ] Docker deployment
- [ ] Kubernetes scaling
- [ ] Mobile app (React Native)
- [ ] Plugin system

