"""
FastAPI Backend para vtool_llama - Chat con Personajes IA

Proporciona endpoints para:
- Listar personajes disponibles
- Cargar personajes
- Chat en streaming (SSE)
- Información del personaje
"""

import sys
import json
import traceback
import asyncio
from typing import AsyncGenerator
from pathlib import Path

from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse, HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Asegurar que el directorio raíz del proyecto esté en sys.path
# main.py está en vtool_llama/examples/simple_chat/, subimos 4 niveles hasta la raíz del repo
_project_root = Path(__file__).parent.parent.parent.parent.resolve()
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# Importar vtool_llama
from vtool_llama import VToolLlama  # noqa: E402

# ============================================================================
# CONFIGURACIÓN
# ============================================================================

BASE_DIR = Path(__file__).parent
CHARACTERS_DIR = BASE_DIR.parent.parent / "characters"
STATIC_DIR = BASE_DIR  # index.html está en simple_chat/


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Startup and shutdown lifecycle."""
    yield
    global _llm_instance
    if _llm_instance:
        try:
            _llm_instance.unload_model()
        except Exception:
            pass


app = FastAPI(
    title="VTool Llama Chat",
    description="Chat con personajes IA locales",
    version="0.3.0",
    lifespan=lifespan
)

# CORS para desarrollo local
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================================
# ESTADO GLOBAL
# ============================================================================

# Mantener una instancia global de VToolLlama
_llm_instance: VToolLlama | None = None
_current_character: str | None = None


def get_llm() -> VToolLlama:
    """Obtiene o crea la instancia global de VToolLlama."""
    global _llm_instance
    if _llm_instance is None:
        _llm_instance = VToolLlama(auto_load=True)
    return _llm_instance


# ============================================================================
# PYDANTIC MODELS
# ============================================================================

class CharacterInfo(BaseModel):
    name: str
    role: str = ""
    background: str = ""
    description: str = ""
    has_soul: bool = False


class ChatRequest(BaseModel):
    message: str
    character: str


class CharacterState(BaseModel):
    current_character: str | None
    state_info: dict | None = None


# ============================================================================
# ENDPOINTS
# ============================================================================

@app.get("/", response_class=HTMLResponse)
async def root():
    """Sirve la página principal HTML."""
    html_path = STATIC_DIR / "index.html"
    if html_path.exists():
        return FileResponse(html_path)
    # Fallback si no existe el archivo
    return HTMLResponse(
        "<h1>VTool Llama Chat</h1><p>Abre /static/index.html en tu navegador</p>"
    )


@app.get("/api/characters", response_model=list[CharacterInfo])
async def list_characters():
    """Lista todos los personajes disponibles."""
    try:
        llm = get_llm()
        chars = llm.list_characters()

        result = []
        for name in chars:
            # Leer identity.json si existe
            dna_dir = CHARACTERS_DIR / name / "dna"
            identity_path = dna_dir / "identity.json"

            char_info = CharacterInfo(name=name)

            if identity_path.exists():
                try:
                    with open(identity_path, encoding='utf-8') as f:
                        ident = json.load(f)
                    char_info.role = ident.get('role', '')
                    char_info.background = ident.get('background', '')
                    char_info.description = ident.get('description', '')
                except Exception as e:
                    print(f"Error leyendo {identity_path}: {e}")

            # Verificar si tiene soul
            soul_path = CHARACTERS_DIR / name / "soul" / "soul.json"
            char_info.has_soul = soul_path.exists()

            result.append(char_info)

        return result

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


class LoadCharacterRequest(BaseModel):
    character: str


@app.post("/api/load-character")
async def load_character(req: LoadCharacterRequest):
    """Carga un personaje específico."""
    global _current_character
    character = req.character

    try:
        llm = get_llm()

        # Validar que el personaje existe
        chars = llm.list_characters()
        if character not in chars:
            raise HTTPException(
                status_code=404,
                detail=f"Personaje '{character}' no encontrado"
            )

        # Cargar el personaje
        llm.load_character(character, semantic_memory=True)
        _current_character = character

        # Obtener estado
        state_info = llm.get_state_info()

        return {
            "success": True,
            "character": character,
            "state_info": state_info
        }

    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@app.get("/api/character-state")
async def character_state():
    """Obtiene el estado actual del personaje cargado."""
    try:
        llm = get_llm()
        state_info = llm.get_state_info() if _current_character else None

        return CharacterState(
            current_character=_current_character,
            state_info=state_info
        )

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@app.post("/api/chat")
async def chat(request: ChatRequest):
    """Chat simple (respuesta completa)."""
    try:
        if _current_character != request.character:
            raise HTTPException(
                status_code=400,
                detail=f"Personaje '{request.character}' no cargado"
            )

        llm = get_llm()
        response = llm.chat(request.message)

        return {
            "success": True,
            "response": response,
            "character": request.character
        }

    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@app.post("/api/chat-stream")
async def chat_stream(request: ChatRequest):
    """Chat con streaming (SSE)."""
    try:
        if _current_character != request.character:
            raise HTTPException(
                status_code=400,
                detail=f"Personaje '{request.character}' no cargado"
            )

        llm = get_llm()

        async def event_generator() -> AsyncGenerator[str, None]:
            """Genera eventos SSE con tokens del chat."""
            try:
                for token in llm.stream_chat(request.message):
                    if isinstance(token, str):
                        # Escapar para SSE
                        escaped = token.replace('\n', '\\n')
                        yield f"data: {escaped}\n\n"
                    await asyncio.sleep(0)  # Permitir otras tareas

                yield "data: [DONE]\n\n"

            except Exception as e:
                yield f"data: [ERROR] {str(e)}\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@app.post("/api/reset")
async def reset_chat():
    """Limpia el historial de chat del personaje actual."""
    try:
        if not _current_character:
            raise HTTPException(
                status_code=400,
                detail="No hay personaje cargado"
            )

        llm = get_llm()
        llm.reset_chat()

        return {"success": True, "message": "Chat reiniciado"}

    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@app.post("/api/save-episode")
async def save_episode():
    """Guarda un snapshot del episodio actual."""
    try:
        if not _current_character:
            raise HTTPException(
                status_code=400,
                detail="No hay personaje cargado"
            )

        llm = get_llm()
        episode_id = llm.save_episode()

        return {
            "success": True,
            "episode_id": episode_id,
            "message": "Episodio guardado"
        }

    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@app.get("/api/episodes")
async def list_episodes():
    """Lista todos los episodios del personaje actual."""
    try:
        if not _current_character:
            raise HTTPException(
                status_code=400,
                detail="No hay personaje cargado"
            )
        
        llm = get_llm()
        episodes = llm.list_episodes()
        return {
            "success": True,
            "episodes": episodes
        }
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


class LoadEpisodeRequest(BaseModel):
    episode_id: int


@app.post("/api/load-episode")
async def load_episode(req: LoadEpisodeRequest):
    """Carga un episodio específico (rollback)."""
    try:
        if not _current_character:
            raise HTTPException(
                status_code=400,
                detail="No hay personaje cargado"
            )
        
        llm = get_llm()
        llm.load_episode(req.episode_id)
        
        # Obtener memoria actualizada
        memory = llm.get_memory()
        
        return {
            "success": True,
            "episode_id": req.episode_id,
            "message": f"Episodio {req.episode_id} cargado con éxito",
            "memory": memory
        }
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@app.delete("/api/episodes/{episode_id}")
async def delete_episode(episode_id: int):
    """Elimina un episodio específico."""
    try:
        if not _current_character:
            raise HTTPException(
                status_code=400,
                detail="No hay personaje cargado"
            )
        
        llm = get_llm()
        ok = llm.delete_episode(episode_id)
        
        if not ok:
            raise HTTPException(
                status_code=404,
                detail=f"Episodio {episode_id} no encontrado o no se pudo eliminar"
            )
            
        return {
            "success": True,
            "message": f"Episodio {episode_id} eliminado con éxito"
        }
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@app.get("/api/memory")
async def get_memory():
    """Obtiene el historial de memoria actual."""
    try:
        if not _current_character:
            raise HTTPException(
                status_code=400,
                detail="No hay personaje cargado"
            )

        llm = get_llm()
        memory = llm.get_memory()

        return {
            "character": _current_character,
            "memory": memory
        }

    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@app.get("/health")
async def health():
    """Health check."""
    try:
        llm = get_llm()
        model_info = llm.get_model_info()
        return {
            "status": "ok",
            "current_character": _current_character,
            "model": model_info.get('model_name', 'unknown') if model_info else None
        }
    except Exception as e:
        return {"status": "error", "detail": str(e)}


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=3050,
        log_level="info"
    )
