# VTool Llama Chat Web

Aplicación web moderna para conversar con personajes IA locales usando **FastAPI** y **vtool_llama**.

## 🚀 Requisitos Previos

- **Python 3.11+**
- **Windows 10/11** con NVIDIA GPU (RTX 3050 o superior)
- **CUDA Toolkit 12.1 o 12.4** instalado en el sistema
- **vtool_llama 0.3.0+** instalado

## 📦 Instalación

### 1. Clonar/Descargar el Proyecto

```bash
cd /ruta/del/proyecto
```

### 2. Instalar Dependencias FastAPI

```bash
pip install -r requirements.txt
```

### 3. Instalar vtool_llama (si no está instalado)

```bash
# Desde tu directorio de vtool_llama
pip install -e /ruta/a/vtool_llama
```

O si está en PyPI:

```bash
pip install vtool_llama>=0.3.0
```

### 4. Configurar Rutas (si es necesario)

En `main.py`, asegúrate de que las rutas sean correctas:

```python
PERSONAJES_DIR = BASE_DIR / "personajes"  # Ajusta según tu estructura
```

Si tus personajes están en otra ubicación, modifica `BASE_DIR` o `PERSONAJES_DIR` para que apunte al directorio correcto.

## ▶️ Ejecutar la Aplicación

### Opción A: Con Uvicorn

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Opción B: Con Python directo

```bash
python main.py
```

### Opción C: Con Gunicorn (Producción)

```bash
pip install gunicorn
gunicorn -w 1 -k uvicorn.workers.UvicornWorker main:app --bind 0.0.0.0:8000
```

## 🌐 Acceder a la Aplicación

Abre tu navegador en:

```
http://localhost:8000
```

O en la IP de tu máquina:

```
http://<tu-ip>:8000
```

## 💡 Cómo Usar

1. **Selecciona un Personaje**: En el sidebar izquierdo, haz clic en un personaje para cargarlo
2. **Escribe un Mensaje**: En el campo de input, escribe tu mensaje
3. **Envía**: Presiona Enter o haz clic en el botón 📤
4. **Respuesta en Streaming**: Verás la respuesta aparecer token por token en tiempo real

### Controles Disponibles

- **🔄 Reset**: Limpia el historial de chat del personaje actual
- **💾 Guardar**: Guarda un snapshot (episodio) de la conversación actual
- **Shift+Enter**: Nueva línea en el input (Enter solo envía)

## 📡 API Endpoints

### Personajes

```
GET /api/characters
```

Obtiene lista de personajes disponibles con información.

```json
[
  {
    "name": "Ares",
    "role": "Guerrero mitológico",
    "background": "...",
    "description": "...",
    "has_soul": true
  }
]
```

### Cargar Personaje

```
POST /api/load-character
Content-Type: application/json

{
  "character": "nombre_del_personaje"
}
```

Respuesta:

```json
{
  "success": true,
  "character": "Ares",
  "state_info": { ... }
}
```

### Chat Simple

```
POST /api/chat
Content-Type: application/json

{
  "message": "Hola, ¿cómo estás?",
  "character": "Ares"
}
```

Respuesta:

```json
{
  "success": true,
  "response": "Texto de la respuesta del personaje",
  "character": "Ares"
}
```

### Chat con Streaming (SSE)

```
POST /api/chat-stream
Content-Type: application/json

{
  "message": "Explícame algo",
  "character": "Ares"
}
```

El servidor envía eventos SSE con tokens individuales.

### Reset Chat

```
POST /api/reset
```

Limpia el historial de chat del personaje actual.

### Guardar Episodio

```
POST /api/save-episode
```

Guarda un snapshot de la conversación actual.

```json
{
  "success": true,
  "episode_id": "uuid-del-episodio",
  "message": "Episodio guardado"
}
```

### Listar Episodios

```
GET /api/episodes
```

Lista todos los episodios guardados del personaje cargado.

Respuesta:

```json
{
  "success": true,
  "episodes": [
    {
      "file": "episode_001.json",
      "episode_id": 1,
      "timestamp": "2026-05-28T16:12:26",
      "summary": "Resumen...",
      "message_count": 2
    }
  ]
}
```

### Cargar/Restaurar Episodio (Rollback)

```
POST /api/load-episode
Content-Type: application/json

{
  "episode_id": 1
}
```

Restaura el historial de conversación de corto plazo al punto de ese episodio y ejecuta de forma automática el **rollback cronológico** en la DB de ChromaDB, eliminando turnos vectoriales posteriores.

Respuesta:

```json
{
  "success": true,
  "episode_id": 1,
  "message": "Episodio 1 cargado con éxito",
  "memory": [ ... ]
}
```

### Eliminar Episodio

```
DELETE /api/episodes/{episode_id}
```

Elimina la copia física de restauración del episodio indicado por su ID numérico.

Respuesta:

```json
{
  "success": true,
  "message": "Episodio 1 eliminado con éxito"
}
```

### Estado del Personaje

```
GET /api/character-state
```

Obtiene el estado actual del personaje cargado.

### Memoria

```
GET /api/memory
```

Obtiene el historial de memoria del personaje.

### Health Check

```
GET /health
```

Verifica el estado de la aplicación.

```json
{
  "status": "ok",
  "current_character": "Ares",
  "model": "Qwen3-8B-Q4_K_M.gguf"
}
```

## 🎨 Personalización

### Cambiar Tema

En `index.html`, modifica las variables CSS:

```css
:root {
  --primary: #0f172a;
  --accent: #3b82f6;
  --success: #10b981;
  /* etc */
}
```

### Cambiar Host/Puerto

En `main.py`:

```python
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host="127.0.0.1",  # Localhost solo
        port=5000          # Puerto personalizado
    )
```

### Configurar Rutas de Personajes

En `main.py`:

```python
BASE_DIR = Path(__file__).parent
PERSONAJES_DIR = Path("C:/ruta/a/personajes")  # Tu ruta personalizada
```

## 🐛 Debugging

### Ver Logs de Debug

En `main.py`, set `enable_debug()`:

```python
llm = VToolLlama(auto_load=True)
llm.enable_debug()
```

### Ejecutar con Debug Logging

```bash
uvicorn main:app --reload --log-level debug
```

### Verificar Modelos

```bash
python -c "from vtool_llama import VToolLlama; llm = VToolLlama(auto_load=True); print(llm.get_model_info())"
```

## 📋 Estructura de Archivos

```
proyecto/
├── main.py                 # Backend FastAPI
├── index.html              # Frontend (sirvase como static)
├── requirements.txt        # Dependencias Python
├── README.md               # Este archivo
├── config.json             # Config de vtool_llama (opcional)
└── personajes/
    ├── Ares/
    ├── Sofia/
    └── ...
```

## 🚨 Problemas Comunes

### "No hay personajes disponibles"

1. Verifica que `PERSONAJES_DIR` apunte al directorio correcto
2. Asegúrate de que existen carpetas de personajes en ese directorio
3. Verifica permisos de lectura

### "Error al cargar el modelo"

1. Verifica que CUDA esté correctamente instalado: `nvcc --version`
2. Asegúrate de que el modelo GGUF existe en `models_directory`
3. Verifica que tienes suficiente VRAM disponible

### El streaming es muy lento

1. Reduce `gpu_layers` en `config.json`
2. Cambia a un modelo más pequeño (ej: 3B en lugar de 8B)
3. Aumenta `temperature` para respuestas más cortas

### "Connection refused" al acceder a `localhost:8000`

1. Verifica que el servidor esté corriendo: busca "Uvicorn running" en la terminal
2. Intenta acceder a `http://127.0.0.1:8000` explícitamente
3. Verifica que el puerto 8000 no esté ocupado: `netstat -ano | findstr 8000`

## 📝 Notas de Desarrollo

- El frontend es **vanilla JavaScript** (sin frameworks) para máxima compatibilidad
- El streaming usa **Server-Sent Events (SSE)** para respuestas en tiempo real
- La instancia de `VToolLlama` se mantiene global para eficiencia
- El caché KV se persiste entre requests
- La psicología del personaje evoluciona durante la conversación

## 🔒 Seguridad (Producción)

Para desplegar en producción:

1. **Usa HTTPS**:

```bash
pip install python-multipart aiofiles
# Configura con certbot/Let's Encrypt
```

2. **Desactiva CORS abierto**:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://tu-dominio.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

3. **Añade rate limiting**:

```bash
pip install slowapi
```

4. **Usa Gunicorn con múltiples workers**:

```bash
gunicorn -w 4 -k uvicorn.workers.UvicornWorker main:app
```

**Nota**: Con `n_gpu_layers = -1`, usa 1 worker. Para múltiples workers, cambia a `n_gpu_layers = 20`.

## 📚 Recursos

- [FastAPI Docs](https://fastapi.tiangolo.com)
- [vtool_llama Docs](../README.md)
- [Uvicorn](https://www.uvicorn.org)
- [SSE (Server-Sent Events)](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events)

## 📄 Licencia

MIT
