import pytest
import socketio
import threading
import time

from app import app, socketio

@pytest.fixture(scope="module")
def test_client():
    return app.test_client()

def test_health_endpoint(test_client):
    resp = test_client.get("/api/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "ok"
    assert "symbols" in data
    assert isinstance(data["symbols"], list)

def test_prices_namespace_emits_init_candles():
    # Start Socket.IO server in background thread
    def run_server():
        socketio.run(app, host="127.0.0.1", port=5055)

    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    time.sleep(1)  # Give server time to start

    sio_client = socketio.Client()

    received_init = {}

    @sio_client.on("init_candles", namespace="/prices")
    def on_init_candles(data):
        received_init["data"] = data
        sio_client.disconnect()

    sio_client.connect("http://127.0.0.1:5055", namespaces=["/prices"])
    sio_client.wait()

    assert "data" in received_init, "Did not receive init_candles event"
    assert isinstance(received_init["data"], list)
