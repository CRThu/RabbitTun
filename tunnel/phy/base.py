from abc import ABC, abstractmethod


class PhysicalLayer(ABC):
    @abstractmethod
    def open(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    @abstractmethod
    def send(self, data: bytes) -> None: ...

    @abstractmethod
    def recv(self, timeout: float | None = None) -> bytes: ...
