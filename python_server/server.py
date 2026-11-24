import asyncio
import json
import websockets
import json

from bleak import BleakScanner, BleakClient

SERVICE_UUID = "8e400001-b5a3-f393-a8e9-4bd8c1c5b2a4"
RX_UUID = "8e400002-b5a3-f393-a8e9-4bd8c1c5b2a4"
TX_UUID = "8e400003-b5a3-f393-a8e9-4bd8c1c5b2a4"

DEVICE_NAME = "ESP32 Ploter"

PEN_DOWN = "M3"
PEN_UP = "M5"
FEED = 1500

client = None
ack_event = asyncio.Event()
send_lock = asyncio.Lock()
ws_clients = set()

async def broadcast(data):
    message = json.dumps(data)

    for ws in list(ws_clients):
        try:
            await ws.send(message)
        except websockets.ConnectionClosed:
            ws_clients.discard(ws)


def notification_handler(sender, data):
    message = data.decode(errors="ignore").strip()

    print("ESP32:", message)

    if message == "ok":
        ack_event.set()


async def bluetooth_worker():

    global client

    while True:

        print("Searching for ESP32...")

        await broadcast({"status": "searching"})

        try:
            devices = await BleakScanner.discover(timeout=5)

            device = next(
                (d for d in devices if d.name == DEVICE_NAME),
                None
            )

            if device is None:
                await asyncio.sleep(2)
                continue

            await broadcast({"status": "connecting"})

            client = BleakClient(device)
            await client.connect()

            await client.start_notify(
                TX_UUID,
                notification_handler
            )

            print("ESP32 CONNECTED!")

            await broadcast({"status": "connected"})

            while client.is_connected:
                await asyncio.sleep(1)

        except Exception as e:
            print("Bluetooth error:", e)

        finally:
            if client and client.is_connected:
                await client.disconnect()

            client = None

            await broadcast({"status": "disconnected"})

        await asyncio.sleep(2)


async def send_gcode(commands):

    async with send_lock:

        if not client or not client.is_connected:
            raise RuntimeError("ESP32 is not connected")

        for i, command in enumerate(commands):

            ack_event.clear()

            await client.write_gatt_char(
                RX_UUID,
                (command + "\n").encode(),
                response=True
            )

            try:
                await asyncio.wait_for(
                    ack_event.wait(),
                    timeout=5
                )
            except asyncio.TimeoutError:
                raise RuntimeError(
                    f"ESP32 ACK timeout: {command}"
                )

            print(f"Sent: {command}")

            await broadcast({
                "status": "sending",
                "progress": i + 1,
                "total": len(commands),
                "command": command
            })

        await broadcast({"status": "complete"})


async def websocket_handler(ws):

    ws_clients.add(ws)

    try:
        await ws.send(json.dumps({
            "status": "connected"
            if client and client.is_connected
            else "disconnected"
        }))

        async for message in ws:

            data = json.loads(message)

            if data.get("action") == "send":

                try:
                    await send_gcode(data["commands"])

                except Exception as e:

                    await ws.send(json.dumps({
                        "status": "error",
                        "message": str(e)
                    }))

    finally:
        ws_clients.discard(ws)

        
async def main():

    asyncio.create_task(bluetooth_worker())

    async with websockets.serve(
        websocket_handler,
        "127.0.0.1",
        8765
    ):

        print("Plotter server started!")
        print("Website: http://localhost:8000")
        print("WebSocket: ws://127.0.0.1:8765")

        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
