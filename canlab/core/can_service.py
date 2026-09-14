"""Central CAN ownership, safe transmission, and receive distribution.

The lightweight :class:`SafeBusAdapter` is also used when protocol classes are
constructed with a bare test or third-party Bus.  Production connections use
``CanCoordinator`` (implemented below) so the raw Bus is never exposed.
"""
from __future__ import annotations

from contextlib import contextmanager, nullcontext
import queue
import threading
from typing import Any, Callable, Collection

from core.safety import require_armed


class SafeBusAdapter:
    """Bus-compatible adapter that checks ARM TX immediately before sending."""

    _canlab_safe_sender = True

    def __init__(self, bus: Any):
        self._bus = bus

    def send(self, message: Any, timeout: float | None = None):
        """Send one frame only when the global transmit gate is armed."""
        require_armed()
        if timeout is None:
            return self._bus.send(message)
        return self._bus.send(message, timeout=timeout)

    def __getattr__(self, name: str):
        return getattr(self._bus, name)


def secure_bus(bus: Any) -> Any:
    """Return a safe sender without stacking duplicate adapters."""
    if getattr(bus, "_canlab_safe_sender", False):
        return bus
    return SafeBusAdapter(bus)


def bus_transaction(bus: Any):
    """Use a routed endpoint's transaction boundary when one is available."""
    transaction = getattr(bus, "transaction", None)
    return transaction() if callable(transaction) else nullcontext()


def protocol_bus(bus: Any, arbitration_ids: Collection[int],
                 transaction_key: object):
    """Use a routed endpoint in production or a safe bare-Bus adapter in tests."""
    if isinstance(bus, CanCoordinator):
        return bus.endpoint(arbitration_ids, transaction_key=transaction_key)
    return secure_bus(bus)


def close_protocol_bus(bus: Any) -> None:
    """Close only coordinator endpoints; never close a caller-owned raw Bus."""
    if isinstance(bus, CanEndpoint):
        bus.close()


class CanServiceClosedError(RuntimeError):
    """Raised when an operation targets a stopped or unavailable CAN service."""


class CanServiceStartError(RuntimeError):
    """Raised when the CAN receiver cannot create or start its Bus."""


_CLOSED = object()


class CanSubscription:
    """A routed receive queue that never calls the physical Bus directly."""

    def __init__(
        self,
        coordinator: "CanCoordinator",
        arbitration_ids: Collection[int] | None = None,
        predicate: Callable[[Any], bool] | None = None,
    ):
        self._coordinator = coordinator
        self._ids = frozenset(int(value) for value in arbitration_ids or ())
        self._predicate = predicate
        self._queue: queue.Queue[Any] = queue.Queue()
        self._closed = False

    def matches(self, message: Any) -> bool:
        if self._closed:
            return False
        if self._ids and getattr(message, "arbitration_id", None) not in self._ids:
            return False
        return self._predicate(message) if self._predicate is not None else True

    def put(self, message: Any) -> None:
        if not self._closed:
            self._queue.put(message)

    def recv(self, timeout: float | None = None):
        if self._closed and self._queue.empty():
            return None
        try:
            item = self._queue.get(timeout=timeout)
        except queue.Empty:
            return None
        return None if item is _CLOSED else item

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._coordinator._remove_subscription(self)
        self._queue.put(_CLOSED)

    def clear_pending(self) -> None:
        """Drop frames routed before this subscription owns its transaction."""
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                return

    def _close_from_coordinator(self) -> None:
        if not self._closed:
            self._closed = True
            self._queue.put(_CLOSED)


class CanEndpoint:
    """Protocol-facing Bus facade backed by one routed subscription."""

    _canlab_safe_sender = True

    def __init__(self, coordinator: "CanCoordinator",
                 subscription: CanSubscription, transaction_key: object | None):
        self._coordinator = coordinator
        self._subscription = subscription
        self._transaction_key = transaction_key

    def send(self, message: Any, timeout: float | None = None):
        return self._coordinator.send(message, timeout=timeout)

    def recv(self, timeout: float | None = None):
        return self._subscription.recv(timeout)

    @contextmanager
    def transaction(self):
        if self._transaction_key is None:
            yield
            return
        with self._coordinator.transaction(self._transaction_key):
            self._subscription.clear_pending()
            yield

    def close(self) -> None:
        self._subscription.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()


class CanCoordinator:
    """Own one physical CAN Bus and provide safe send/routed receive access."""

    _canlab_safe_sender = True

    def __init__(self, *, bus: Any | None = None,
                 bus_factory: Callable[[], Any] | None = None,
                 on_message: Callable[[Any], None] | None = None,
                 on_error: Callable[[str], None] | None = None,
                 receive_timeout: float = 0.05):
        if bus is None and bus_factory is None:
            raise ValueError("bus or bus_factory is required")
        self._bus = bus
        self._bus_factory = bus_factory
        self._on_message = on_message
        self._on_error = on_error
        self._receive_timeout = max(0.001, float(receive_timeout))
        self._send_lock = threading.Lock()
        self._lifecycle_lock = threading.Lock()
        self._subscriptions_lock = threading.Lock()
        self._subscriptions: set[CanSubscription] = set()
        self._transactions_lock = threading.Lock()
        self._transactions: dict[object, threading.RLock] = {}
        self._stop_event = threading.Event()
        self._started = threading.Event()
        self._receiver_stopped = threading.Event()
        self._receiver_thread: threading.Thread | None = None
        self._startup_error: BaseException | None = None
        self._closed = False
        self._closing = False

    @property
    def is_running(self) -> bool:
        thread = self._receiver_thread
        return bool(thread and thread.is_alive() and self._started.is_set()
                    and self._startup_error is None and not self._stop_event.is_set())

    def start(self) -> bool:
        """Start the sole receive thread; repeated starts are idempotent."""
        if self._receiver_thread is not None and self._receiver_thread.is_alive():
            return False
        if self._closed or self._closing:
            raise CanServiceClosedError("CAN coordinator has been stopped")
        self._stop_event.clear()
        self._started.clear()
        self._receiver_stopped.clear()
        self._startup_error = None
        self._receiver_thread = threading.Thread(
            target=self._receive_loop, daemon=True, name="canlab-can-receiver"
        )
        self._receiver_thread.start()
        return True

    def wait_started(self, timeout: float = 5.0) -> bool:
        if not self._started.wait(timeout):
            return False
        if self._startup_error is not None:
            raise CanServiceStartError(str(self._startup_error)) from self._startup_error
        return self._bus is not None and self.is_running

    def send(self, message: Any, timeout: float | None = None):
        """Check ARM TX immediately before the only physical Bus send call."""
        with self._send_lock:
            bus = self._bus
            if self._closed or self._closing or bus is None:
                raise CanServiceClosedError("CAN bus is not available")
            require_armed()
            if timeout is None:
                return bus.send(message)
            return bus.send(message, timeout=timeout)

    def subscribe(self, arbitration_ids: Collection[int] | None = None,
                  predicate: Callable[[Any], bool] | None = None) -> CanSubscription:
        with self._subscriptions_lock:
            if self._closed or self._closing:
                raise CanServiceClosedError("CAN coordinator has been stopped")
            subscription = CanSubscription(self, arbitration_ids, predicate)
            self._subscriptions.add(subscription)
        return subscription

    def endpoint(self, arbitration_ids: Collection[int] | None = None,
                 transaction_key: object | None = None,
                 predicate: Callable[[Any], bool] | None = None) -> CanEndpoint:
        return CanEndpoint(
            self,
            self.subscribe(arbitration_ids=arbitration_ids, predicate=predicate),
            transaction_key,
        )

    def transaction(self, key: object):
        with self._transactions_lock:
            lock = self._transactions.setdefault(key, threading.RLock())
        return lock

    def stop(self, timeout: float = 2.0) -> bool:
        """Wake consumers, join the receiver, then and only then close the Bus."""
        with self._lifecycle_lock:
            if self._closed:
                return True
            with self._send_lock:
                self._closing = True
            self._stop_event.set()
            with self._subscriptions_lock:
                subscriptions = tuple(self._subscriptions)
                self._subscriptions.clear()
            for subscription in subscriptions:
                subscription._close_from_coordinator()

            thread = self._receiver_thread
            if thread is threading.current_thread():
                return False
            if thread is not None:
                thread.join(max(0.0, float(timeout)))
                if thread.is_alive():
                    return False

            bus = self._bus
            if bus is not None:
                bus.shutdown()
            self._closed = True
            self._bus = None
            self._receiver_thread = None
            return True

    def _receive_loop(self) -> None:
        try:
            if self._bus is None:
                self._bus = self._bus_factory()
            if self._bus is None:
                raise CanServiceStartError("CAN bus factory returned no bus")
            self._started.set()
            while not self._stop_event.is_set():
                message = self._bus.recv(timeout=self._receive_timeout)
                if message is None:
                    continue
                if self._on_message is not None:
                    try:
                        self._on_message(message)
                    except Exception as exc:
                        self._report_error(f"CAN capture callback failed: {exc}")
                with self._subscriptions_lock:
                    subscriptions = tuple(self._subscriptions)
                for subscription in subscriptions:
                    try:
                        if subscription.matches(message):
                            subscription.put(message)
                    except Exception as exc:
                        self._report_error(f"CAN subscription failed: {exc}")
        except BaseException as exc:
            if not self._started.is_set():
                self._startup_error = exc
                self._started.set()
            elif not self._stop_event.is_set():
                self._report_error(f"CAN receive failed: {exc}")
        finally:
            self._receiver_stopped.set()

    def _remove_subscription(self, subscription: CanSubscription) -> None:
        with self._subscriptions_lock:
            self._subscriptions.discard(subscription)

    def _report_error(self, message: str) -> None:
        if self._on_error is not None:
            self._on_error(message)
