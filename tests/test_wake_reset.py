import json
import socket
import unittest
from unittest.mock import MagicMock, patch
import pytest

from vani.memory import conversation_writer
from vani.reasoning import worker
from vani.app import _ws_clients, _ws_send_all


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.fixture
def mock_websocket():
    sock = MagicMock(spec=socket.socket)
    with patch("vani.app._ws_clients", {sock}):
        yield sock


def test_ws_send_all(mock_websocket):
    _ws_send_all({"action": "clear_chat"})
    # Verify sock.sendall was called with the encoded frame
    assert mock_websocket.sendall.called


@pytest.mark.anyio
async def test_latest_wins_queue_cancellation():
    q = worker.LatestWinsQueue()

    # Create dummy active task
    async def dummy_task():
        try:
            import asyncio
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            pass

    import asyncio
    active_task = asyncio.create_task(dummy_task())
    q.set_active_task(active_task)

    # Trigger cancellation
    q.cancel_active_task_threadsafe()

    # Yield control to let event loop process cancellation
    await asyncio.sleep(0.01)

    assert active_task.cancelled() or active_task.done()


@pytest.mark.anyio
async def test_latest_wins_queue_future_cancellation():
    q = worker.LatestWinsQueue()
    import asyncio
    future = asyncio.get_event_loop().create_future()

    async def dummy_task():
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            pass

    active_task = asyncio.create_task(dummy_task())
    q.set_active_task(active_task, future)

    # Trigger cancellation
    q.cancel_active_task_threadsafe()

    # Yield control to let event loop process cancellation
    await asyncio.sleep(0.01)

    assert future.done()
    assert future.result() is q._STALE
    assert active_task.cancelled() or active_task.done()


@patch("vani.app._ws_send_all")
@patch("vani.memory.conversation_writer.clear_conversation")
@patch("vani.reasoning.worker._get_task_queue")
@patch("vani.reasoning.worker._session_ref")
@patch("vani.reasoning.worker._session_loop")
@patch("vani.memory.working_memory.clear_working_memory")
@patch("vani.memory.vector_store.SQLiteVectorStore.clear_all")
def test_wake_reset_endpoint_invocations(
    mock_vector_clear, mock_working_clear, mock_loop, mock_session, mock_queue_fn, mock_clear_conv, mock_ws_send
):
    # Mock queue
    mock_queue = MagicMock()
    mock_queue_fn.return_value = mock_queue

    # Simulate HTTP handler call to /wake_reset
    from vani.app import _Handler
    
    # We create a mock handler
    handler = MagicMock(spec=_Handler)
    handler.path = "/wake_reset"
    handler.headers = {}
    
    # Run the do_POST logic
    _Handler.do_POST(handler)

    # 1. Verify clear_conversation was called
    assert mock_clear_conv.called

    # 2. Verify cancel_active_task_threadsafe was called
    assert mock_queue.cancel_active_task_threadsafe.called

    # 3. Verify LiveKit interrupt was scheduled
    assert mock_loop.is_running.called or mock_loop.call_soon_threadsafe.called or mock_session.interrupt.called

    # 4. Verify clear_chat WebSocket broadcast was sent
    mock_ws_send.assert_called_with({"action": "clear_chat"})

    # 5. Verify working memory and vector store clears were called
    assert mock_working_clear.called
    assert mock_vector_clear.called
