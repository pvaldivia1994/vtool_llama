#!/usr/bin/env python3
"""
Script helper para iniciar la aplicación FastAPI de VTool Llama Chat.

Maneja:
- Validación de dependencias
- Configuración de rutas
- Inicio del servidor
- Manejo de errores comunes
"""

import os
import sys
import subprocess
from pathlib import Path
from typing import Optional


def check_python_version():
    """Verifica que Python 3.11+ esté instalado."""
    version = sys.version_info
    if version.major < 3 or (version.major == 3 and version.minor < 11):
        print(f"❌ Error: Se requiere Python 3.11+. Tienes Python {version.major}.{version.minor}")
        sys.exit(1)
    print(f"✓ Python {version.major}.{version.minor}.{version.micro} OK")


def check_dependencies():
    """Verifica que las dependencias estén instaladas."""
    required = ['fastapi', 'uvicorn', 'pydantic', 'vtool_llama']
    missing = []

    for package in required:
        try:
            __import__(package.replace('-', '_'))
            print(f"✓ {package} OK")
        except ImportError:
            missing.append(package)
            print(f"❌ {package} NO INSTALADO")

    if missing:
        print(f"\n⚠️  Falta instalar: {', '.join(missing)}")
        print("\nEjecuta:")
        print("  pip install -r requirements.txt")
        print(f"  pip install vtool_llama  # o desde tu directorio local")
        sys.exit(1)


def check_personajes_dir():
    """Verifica que el directorio de personajes exista."""
    base_dir = Path(__file__).parent
    personajes_dir = base_dir / "personajes"

    if not personajes_dir.exists():
        print(f"⚠️  Advertencia: Directorio de personajes no encontrado")
        print(f"   Esperado: {personajes_dir}")
        response = input("\n¿Quieres especificar otra ruta? (s/n): ").strip().lower()
        if response == 's':
            custom_path = input("Ruta personalizada: ").strip()
            if Path(custom_path).exists():
                return Path(custom_path)
            else:
                print(f"❌ Ruta no existe: {custom_path}")
                sys.exit(1)
        else:
            print("⚠️  Continuando sin verificación de personajes...")
            return personajes_dir
    else:
        personajes = list(personajes_dir.iterdir())
        if personajes:
            print(f"✓ Directorio de personajes encontrado ({len(personajes)} personajes)")
        else:
            print(f"⚠️  Directorio de personajes existe pero está vacío")
        return personajes_dir


def check_cuda():
    """Verifica que CUDA esté instalado (opcional pero recomendado)."""
    try:
        result = subprocess.run(['nvcc', '--version'], capture_output=True, text=True)
        if result.returncode == 0:
            # Extraer versión
            for line in result.stdout.split('\n'):
                if 'release' in line:
                    print(f"✓ CUDA: {line.strip()}")
                    return True
    except FileNotFoundError:
        print("⚠️  CUDA no encontrado (opcional, pero recomendado para GPU)")
        return False
    except Exception as e:
        print(f"⚠️  Error verificando CUDA: {e}")
        return False


def get_host_port() -> tuple[str, int]:
    """Obtiene host y puerto para el servidor."""
    print("\n=== Configuración del Servidor ===")
    print("1. localhost (solo local)")
    print("2. 0.0.0.0 (red local)")
    print("3. Personalizado")

    choice = input("Selecciona (1-3) [1]: ").strip() or "1"

    host_map = {"1": "127.0.0.1", "2": "0.0.0.0"}
    host = host_map.get(choice, "127.0.0.1")

    if choice == "3":
        host = input("Host (ej: 192.168.1.100): ").strip() or "127.0.0.1"

    port_input = input("Puerto [8000]: ").strip() or "8000"
    try:
        port = int(port_input)
    except ValueError:
        port = 8000

    return host, port


def check_port_available(port: int) -> bool:
    """Verifica que el puerto esté disponible."""
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex(('127.0.0.1', port))
    sock.close()
    return result != 0


def main():
    print("""
    ╔═══════════════════════════════════════════╗
    ║    VTool Llama Chat - FastAPI Launcher    ║
    ║            v0.3.0                         ║
    ╚═══════════════════════════════════════════╝
    """)

    # Verificaciones
    print("\n=== Verificando Dependencias ===")
    check_python_version()
    check_dependencies()
    personajes_dir = check_personajes_dir()
    cuda_available = check_cuda()

    # Config del servidor
    host, port = get_host_port()

    # Verificar puerto
    if not check_port_available(port):
        print(f"❌ Error: Puerto {port} ya está en uso")
        print(f"Intenta con otro puerto o mata el proceso que lo usa:")
        if sys.platform == "win32":
            print(f"  netstat -ano | findstr {port}")
        else:
            print(f"  lsof -i :{port}")
        sys.exit(1)

    # Mostrar resumen
    print(f"\n=== Configuración Final ===")
    print(f"Host: {host}")
    print(f"Puerto: {port}")
    print(f"Personajes: {personajes_dir}")
    print(f"CUDA: {'✓' if cuda_available else '✗'}")

    url = f"http://{host if host != '0.0.0.0' else 'localhost'}:{port}"
    print(f"\n🌐 Acceso: {url}")

    print(f"\n▶️  Iniciando servidor...")
    print(f"Presiona Ctrl+C para detener\n")

    try:
        subprocess.run([
            sys.executable, '-m', 'uvicorn',
            'main:app',
            '--host', host,
            '--port', str(port),
            '--reload'
        ])
    except KeyboardInterrupt:
        print("\n\n👋 Servidor detenido")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
