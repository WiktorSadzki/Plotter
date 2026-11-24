
import subprocess
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

processes = []

try:
    print("Starting Bluetooth server...")
    ble = subprocess.Popen([sys.executable, str(BASE_DIR / "server.py")])
    processes.append(ble)

    time.sleep(1)

    print("Starting website server...")
    web = subprocess.Popen([
        sys.executable,
        "-m", "http.server", "8000"
    ])
    processes.append(web)

    print("\nBoth servers started!")
    print("Website: http://localhost:8000")
    print("WebSocket: ws://127.0.0.1:8765")
    print("\nPress CTRL+C to stop both servers.")

    while True:
        for p in processes:
            if p.poll() is not None:
                raise RuntimeError("A server stopped unexpectedly")
        time.sleep(1)

except KeyboardInterrupt:
    print("\nStopping servers...")

except Exception as e:
    print("Error:", e)

finally:
    for p in processes:
        if p.poll() is None:
            p.terminate()

    for p in processes:
        try:
            p.wait(timeout=3)
        except subprocess.TimeoutExpired:
            p.kill()

    print("All servers stopped.")
