"""QThread wrapper for one-shot headless CAN operations."""
from PyQt6.QtCore import QThread, pyqtSignal


class CanOperationWorker(QThread):
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, function, *args, parent=None, **kwargs):
        super().__init__(parent)
        self._function = function
        self._args = args
        self._kwargs = kwargs

    def run(self):
        try:
            result = self._function(*self._args, **self._kwargs)
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.succeeded.emit(result)

    def stop(self):
        self.requestInterruption()
