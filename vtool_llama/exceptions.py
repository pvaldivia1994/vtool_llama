"""
Módulo de excepciones personalizadas para vtool_llama.

Define una jerarquía de errores específicos del dominio para
diferenciar fallos técnicos (CUDA, OOM) de errores de uso
(modelo inexistente, prompt vacío, configuración corrupta).

Todas las excepciones heredan de VToolLlamaError como clase
base, lo que permite al proyecto principal capturarlas con un
solo except si no necesita granularidad.
"""


class VToolLlamaError(Exception):
    """
    Excepción base de toda la librería.
    Cualquier error lanzado por vtool_llama hereda de esta clase.
    """
    pass


class ModelNotFoundError(VToolLlamaError):
    """
    El archivo GGUF especificado no existe en la ruta indicada.
    Se lanza durante load_model() si el path no es válido.
    """
    pass


class InvalidModelError(VToolLlamaError):
    """
    El archivo existe pero no es un GGUF válido o está corrupto.
    llama-cpp-python puede lanzar esto si el formato es incorrecto.
    """
    pass


class CUDAUnavailableError(VToolLlamaError):
    """
    No se detectó CUDA en el sistema.
    El modelo puede cargarse en CPU como fallback, pero si el
    usuario requiere GPU explícitamente, se lanza esta excepción.
    """
    pass


class OOMError(VToolLlamaError):
    """
    Out Of Memory — la VRAM o RAM es insuficiente para el modelo
    solicitado con la configuración actual (n_ctx, gpu_layers).
    """
    pass


class EmptyPromptError(VToolLlamaError):
    """
    El usuario envió un prompt vacío o compuesto solo de espacios.
    Se valida antes de cualquier inferencia.
    """
    pass


class ConfigError(VToolLlamaError):
    """
    El archivo config.json está corrupto, tiene formato inválido,
    o falta una clave obligatoria.
    """
    pass


class InferenceError(VToolLlamaError):
    """
    Error durante la inferencia del modelo.
    Puede originarse en llama-cpp-python por contexto saturado,
    tokens inválidos, o fallos internos del backend.
    """
    pass


class ModelNotLoadedError(VToolLlamaError):
    """
    Se intentó generar una respuesta sin tener un modelo cargado.
    Ocurre si se llama a chat() o stream_chat() sin load_model().
    """
    pass


class ContextOverflowError(VToolLlamaError):
    """
    El contexto excedió el límite definido (n_ctx) y no se pudo
    recuperar automáticamente con auto_trim_context.
    """
    pass


class LoadCancelledError(VToolLlamaError):
    """
    La carga de un personaje fue cancelada externamente
    (nueva solicitud de carga, refresh de página, etc.).
    Interna — no se propaga al usuario final.
    """
    pass
