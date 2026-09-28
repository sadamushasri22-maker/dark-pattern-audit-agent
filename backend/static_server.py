import socket
import threading
import logging
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_server_thread: Optional[threading.Thread] = None
_httpd: Optional[ThreadingHTTPServer] = None


def is_port_in_use(port: int = 9000) -> bool:
    """Checks whether the specified port is already open."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def start_static_server(port: int = 9000, directory: Optional[Path] = None) -> bool:
    """
    Starts local static server for sample_sites/ on port 9000.
    Runs in a background daemon thread.
    """
    global _server_thread, _httpd

    if is_port_in_use(port):
        logger.info(f"Port {port} is already active and serving static files.")
        return True

    sample_dir = directory or (Path(__file__).resolve().parent.parent / "sample_sites")
    if not sample_dir.exists():
        logger.error(f"Sample sites directory not found at {sample_dir}")
        return False

    class QuietHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(sample_dir), **kwargs)

        def log_message(self, format, *args):
            # Suppress normal access logs to keep terminal output clean
            pass

    try:
        _httpd = ThreadingHTTPServer(("127.0.0.1", port), QuietHandler)
        _server_thread = threading.Thread(target=_httpd.serve_forever, daemon=True)
        _server_thread.start()
        logger.info(f"Started local sample_sites server on http://localhost:{port} (serving {sample_dir})")
        return True
    except Exception as e:
        logger.error(f"Failed to start static server on port {port}: {e}")
        return False


def stop_static_server() -> None:
    """
    Stops the local static server cleanly on backend shutdown.
    """
    global _server_thread, _httpd

    if _httpd:
        try:
            logger.info("Stopping local sample_sites static server on port 9000...")
            _httpd.shutdown()
            _httpd.server_close()
        except Exception as e:
            logger.warning(f"Error while stopping static server: {e}")
        finally:
            _httpd = None
            _server_thread = None


def ensure_static_server_running(port: int = 9000, directory: Optional[Path] = None) -> bool:
    """Convenience alias for start_static_server."""
    return start_static_server(port=port, directory=directory)


if __name__ == "__main__":
    start_static_server()
    print("Static server running on http://localhost:9000. Press Ctrl+C to stop.")
    import time
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping server.")
        stop_static_server()
