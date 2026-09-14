"""Shared mechanics for tab-owned Qt worker and timer shutdown."""
from __future__ import annotations


def shutdown_owned(owner, *, worker_attrs=(), timer_attrs=(), timeout_ms=2000):
    """Stop resources declared by a tab and report every failed shutdown."""
    errors = []
    for attr in timer_attrs:
        timer = getattr(owner, attr, None)
        if timer is not None:
            try:
                timer.stop()
            except Exception as exc:
                errors.append(f"{attr}: {exc}")

    for attr in worker_attrs:
        worker = getattr(owner, attr, None)
        if worker is None:
            continue
        try:
            if hasattr(worker, "stop"):
                worker.stop()
            else:
                if hasattr(worker, "requestInterruption"):
                    worker.requestInterruption()
                if hasattr(worker, "quit"):
                    worker.quit()
            if hasattr(worker, "isRunning") and worker.isRunning():
                if not worker.wait(timeout_ms):
                    raise TimeoutError(
                        f"did not stop within {timeout_ms} milliseconds"
                    )
            setattr(owner, attr, None)
        except Exception as exc:
            errors.append(f"{attr}: {exc}")

    if errors:
        raise RuntimeError("; ".join(errors))


class LifecycleTabMixin:
    """Lets each tab declare, and therefore own, its background resources."""
    worker_attrs = ()
    timer_attrs = ()
    worker_collections = ()
    shutdown_timeout_ms = 2000

    def worker_slot_available(self, attr: str) -> bool:
        """Reject replacement until the previous worker has fully exited."""
        worker = getattr(self, attr, None)
        if worker is None:
            return True
        if hasattr(worker, "isRunning") and worker.isRunning():
            return False
        setattr(self, attr, None)
        return True

    def shutdown(self):
        errors = []
        try:
            shutdown_owned(
                self,
                worker_attrs=self.worker_attrs,
                timer_attrs=self.timer_attrs,
                timeout_ms=self.shutdown_timeout_ms,
            )
        except Exception as exc:
            errors.append(str(exc))
        for attr in self.worker_collections:
            workers = list(getattr(self, attr, ()) or ())
            collection_failed = False
            for index, worker in enumerate(workers):
                holder = type("WorkerHolder", (), {})()
                holder.worker = worker
                try:
                    shutdown_owned(
                        holder,
                        worker_attrs=("worker",),
                        timeout_ms=self.shutdown_timeout_ms,
                    )
                except Exception as exc:
                    collection_failed = True
                    errors.append(f"{attr}[{index}]: {exc}")
            if not collection_failed:
                getattr(self, attr).clear()
        if errors:
            raise RuntimeError("; ".join(errors))
