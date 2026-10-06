"""An owned POSIX pseudo-terminal with bounded nonblocking reads and writes."""

import asyncio
import errno
import fcntl
import os
import pty
import struct
import termios

from kubetrol.domain.terminal import terminal_size
from kubetrol.errors import AppError


class PtyEndpoint:
    def __init__(self, width: int, height: int) -> None:
        self.loop = asyncio.get_running_loop()
        self.master, self.slave = pty.openpty()
        self.queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=8)
        self.pending = bytearray()
        self.closed = False
        self.eof = False
        self.failure: AppError | None = None
        try:
            os.set_blocking(self.master, False)
            self.resize(width, height)
            self.loop.add_reader(self.master, self._readable)
        except BaseException:
            self.close()
            raise

    def resize(self, width: int, height: int) -> None:
        if not self.closed:
            columns, rows = terminal_size(width, height)
            fcntl.ioctl(self.master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, columns, 0, 0))

    def release_slave(self) -> None:
        if self.slave != -1:
            os.close(self.slave)
            self.slave = -1

    def _end(self, failure: AppError | None = None) -> None:
        self.eof, self.failure = True, failure
        self.loop.remove_reader(self.master)
        if self.queue.empty():
            self.queue.put_nowait(b"")

    def _readable(self) -> None:
        try:
            data = os.read(self.master, 16384)
        except BlockingIOError:
            return
        except OSError as error:
            self._end(None if error.errno == errno.EIO else AppError("Terminal read failed."))
            return
        if not data:
            self._end()
            return
        self.queue.put_nowait(data)
        if self.queue.full():
            self.loop.remove_reader(self.master)

    async def read(self) -> bytes:
        if self.queue.empty() and self.eof:
            if self.failure is not None:
                raise self.failure
            return b""
        value = await self.queue.get()
        if not self.eof:
            self.loop.add_reader(self.master, self._readable)
        if not value and self.failure is not None:
            raise self.failure
        return value

    def write(self, data: bytes) -> None:
        if self.closed or self.eof:
            return
        if len(self.pending) + len(data) > 65536:
            raise AppError("Terminal input is busy; send smaller input after it drains.")
        self.pending.extend(data)
        self._writable()

    def _writable(self) -> None:
        try:
            while self.pending:
                count = os.write(self.master, self.pending)
                if count == 0:
                    raise OSError("no progress")
                del self.pending[:count]
        except BlockingIOError:
            self.loop.add_writer(self.master, self._writable)
            return
        except OSError:
            self.loop.remove_writer(self.master)
            self.pending.clear()
            self._end(AppError("Terminal write failed."))
            return
        self.loop.remove_writer(self.master)

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            self._end()
            self.loop.remove_writer(self.master)
            self.pending.clear()
            self.release_slave()
            os.close(self.master)
