from __future__ import annotations

import os


def main() -> None:
    has_display = os.name == "nt" or bool(os.getenv("DISPLAY"))
    if has_display:
        from desktop_app import main as desktop_main

        desktop_main()
        return

    from app import app as web_app

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "5000"))
    print("Modo headless detectado: iniciando servidor web.")
    print(f"Acesse: http://127.0.0.1:{port} ou http://IP_DO_RASPBERRY:{port}")
    web_app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    main()
