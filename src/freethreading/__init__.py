"""
:mod:`freethreading` is a lightweight wrapper that provides a unified API for true
parallel execution in Python. It automatically uses :mod:`threading` on free-threaded
Python builds (where the GIL is disabled) and falls back to :mod:`multiprocessing` on
standard ones. This enables true parallelism across Python versions while preferring the
efficiency of threads over processes whenever possible.

:mod:`freethreading` is a drop-in replacement for *most* pre-existing :mod:`threading`
and :mod:`multiprocessing` code. To achieve this, the module exposes only non-deprecated
common functionality shared between both backends while discarding any backend-specific
APIs.

Examples
--------
.. code-block:: python

    from freethreading import Worker, WorkerPool, WorkerPoolExecutor, current_worker

    def greet():
        print(f"Hello from {current_worker().name}!")

    def square(x):
        return x * x

    if __name__ == "__main__":
        # MainThread or MainProcess
        print(current_worker().name)

        # Using Worker to distribute work
        w = Worker(target=greet, name="MyWorker")
        w.start()
        w.join()

        # Using WorkerPool to distribute work
        with WorkerPool(workers=2) as pool:
            print(pool.map(square, range(5)))

        # Using WorkerPoolExecutor to distribute work
        with WorkerPoolExecutor(max_workers=2) as executor:
            future = executor.submit(greet)

**Output (Standard Python)**:

.. code-block:: text

    MainProcess
    Hello from MyWorker!
    [0, 1, 4, 9, 16]
    Hello from ForkServerProcess-4!

**Output (Free-threaded Python)**:

.. code-block:: text

    MainThread
    Hello from MyWorker!
    [0, 1, 4, 9, 16]
    Hello from ThreadPoolExecutor-0_0!

See Also
--------
threading : Threading-based parallelism.
multiprocessing : Process-based parallelism.
concurrent.futures : High-level interface for asynchronous execution.
"""

import io
import pickle
import sys
from functools import cache
from multiprocessing.context import (
    get_spawning_popen,
    set_spawning_popen,
)
from multiprocessing.process import BaseProcess
from multiprocessing.reduction import dump
from threading import Thread
from typing import Literal


@cache
def get_backend() -> Literal["threading", "multiprocessing"]:
    """
    Get the name of the active concurrency backend.

    Returns
    -------
    Literal['threading', 'multiprocessing']
        'threading' when GIL is disabled, and 'multiprocessing' otherwise.
    """
    if getattr(sys, "_is_gil_enabled", lambda: True)():
        return "multiprocessing"
    return "threading"


@cache
def _get_mp_context():
    """
    Return the multiprocessing context used to spawn processes and primitives.

    This function returns a cached context based on the platform: 'spawn' on Windows and
    macOS, 'forkserver' otherwise. This avoids 'fork' which is unsafe with threads. It
    should only be called when running in multiprocessing backend mode.
    """
    from multiprocessing import get_context

    if get_backend() == "threading":
        raise AssertionError(
            "Attempting to get multiprocessing context while on threading backend"
        )
    if sys.platform in ("win32", "darwin"):
        return get_context("spawn")
    return get_context("forkserver")


if get_backend() == "threading":
    from concurrent.futures import ThreadPoolExecutor as _WorkerPoolExecutor
    from multiprocessing.pool import ThreadPool as _WorkerPool
    from queue import Queue as _Queue
    from queue import SimpleQueue as _SimpleQueue
    from threading import Barrier as _Barrier
    from threading import BoundedSemaphore as _BoundedSemaphore
    from threading import Condition as _Condition
    from threading import Event as _Event
    from threading import Lock as _Lock
    from threading import RLock as _RLock
    from threading import Semaphore as _Semaphore
    from threading import Thread as _Worker
    from threading import active_count as _active_count
    from threading import current_thread as _current_worker
    from threading import enumerate as _enumerate
    from threading import get_ident as _get_ident

    def _active_children():
        children = list(_enumerate())
        children.remove(_current_worker())
        return children

else:
    from concurrent.futures import ProcessPoolExecutor as _WorkerPoolExecutor
    from multiprocessing import active_children as _active_children
    from multiprocessing import current_process as _current_worker
    from os import getpid as _get_ident

    _Barrier = _get_mp_context().Barrier
    _BoundedSemaphore = _get_mp_context().BoundedSemaphore
    _Condition = _get_mp_context().Condition
    _Event = _get_mp_context().Event
    _Lock = _get_mp_context().Lock
    _RLock = _get_mp_context().RLock
    _Semaphore = _get_mp_context().Semaphore
    _Queue = _get_mp_context().JoinableQueue
    _SimpleQueue = _get_mp_context().SimpleQueue
    _Worker = _get_mp_context().Process
    _WorkerPool = _get_mp_context().Pool

    def _active_count():
        return len(_enumerate())

    def _enumerate():
        workers = list(_active_children())
        workers.append(_current_worker())
        return workers


class _DummyPopen:
    """Dummy Popen for picklability validation with ForkingPickler."""

    @staticmethod
    def duplicate_for_child(fd):
        return fd

    class DupFd:
        def __init__(self, fd):
            self.fd = fd


class Barrier:
    """
    Synchronization barrier for coordinating :class:`Worker` objects.

    A barrier is used to wait for a fixed number of workers to reach a
    common point. Uses :class:`threading.Barrier` or
    :class:`multiprocessing.Barrier` depending on backend.

    Parameters
    ----------
    parties : int
        Number of workers required to pass the barrier.
    action : callable, optional
        Function called by one worker when the barrier is passed.
    timeout : float, optional
        Default timeout for :meth:`wait` calls.

    See Also
    --------
    threading.Barrier : :mod:`threading` implementation.
    multiprocessing.Barrier : :mod:`multiprocessing` implementation.

    Examples
    --------
    .. code-block:: python

        from freethreading import Barrier, Worker, current_worker

        def synchronized_task(checkpoint):
            print(f"'{current_worker().name}' reached checkpoint")
            checkpoint.wait()
            print(f"'{current_worker().name}' passed checkpoint")

        if __name__ == "__main__":
            checkpoint = Barrier(3)
            workers = [
                Worker(name=f"Worker-{i}", target=synchronized_task, args=(checkpoint,))
                for i in range(3)
            ]
            for w in workers:
                w.start()
            for w in workers:
                w.join()

    **Output**:

    .. code-block:: text

        'Worker-0' reached checkpoint
        'Worker-1' reached checkpoint
        'Worker-2' reached checkpoint
        'Worker-2' passed checkpoint
        'Worker-0' passed checkpoint
        'Worker-1' passed checkpoint
    """

    def __init__(self, parties, action=None, timeout=None):
        self._barrier = _Barrier(parties, action, timeout)

    def __reduce__(self):
        if get_backend() == "threading":
            return (_raise_unpickle_type_error, ())
        return super().__reduce__()

    def wait(self, timeout=None):
        """
        Wait until all parties have reached the barrier.

        Parameters
        ----------
        timeout : float, optional
            Maximum time to wait in seconds.

        Returns
        -------
        int
            The arrival index (0 to parties-1).

        Raises
        ------
        threading.BrokenBarrierError
            If the barrier is broken or reset.
        """
        return self._barrier.wait(timeout)

    def reset(self):
        """Reset the barrier to its initial empty state."""
        self._barrier.reset()

    def abort(self):
        """Put the barrier into a broken state."""
        self._barrier.abort()

    @property
    def parties(self):
        """The number of workers required to trip the barrier."""
        return self._barrier.parties

    @property
    def n_waiting(self):
        """The number of workers currently waiting at the barrier."""
        return self._barrier.n_waiting

    @property
    def broken(self):
        """Whether the barrier is in a broken state."""
        return self._barrier.broken


class BoundedSemaphore:
    """
    A semaphore that prevents releasing more times than acquired.

    A bounded semaphore guards against excessive releases by raising an error if
    released more times than acquired. Uses :class:`threading.BoundedSemaphore` or
    :class:`multiprocessing.BoundedSemaphore` depending on backend.

    Parameters
    ----------
    value : int, default=1
        Initial value for the semaphore counter.

    See Also
    --------
    threading.BoundedSemaphore : :mod:`threading` implementation.
    multiprocessing.BoundedSemaphore : :mod:`multiprocessing` implementation.

    Examples
    --------
    .. code-block:: python

        from freethreading import BoundedSemaphore, Worker, current_worker

        def limited_resource(sem):
            with sem:
                print(f"'{current_worker().name}': in restricted section")

        if __name__ == "__main__":
            sem = BoundedSemaphore(1)
            workers = [
                Worker(name=f"Worker-{i}", target=limited_resource, args=(sem,))
                for i in range(3)
            ]
            for w in workers:
                w.start()
            for w in workers:
                w.join()

    **Output**:

    .. code-block:: text

        'Worker-0': in restricted section
        'Worker-1': in restricted section
        'Worker-2': in restricted section
    """

    def __init__(self, value=1):
        self._semaphore = _BoundedSemaphore(value)

    def __reduce__(self):
        if get_backend() == "threading":
            return (_raise_unpickle_type_error, ())
        return super().__reduce__()

    def acquire(self, blocking=True, timeout=None):
        """
        Acquire the semaphore, decrementing the counter.

        Parameters
        ----------
        blocking : bool, default=True
            If True, block until the semaphore can be acquired. If False, return
            immediately.
        timeout : float, optional
            Maximum time to wait in seconds when blocking. None means wait forever.

        Returns
        -------
        bool
            True if acquired, False if not acquired (non-blocking or timeout).
        """
        return self._semaphore.acquire(blocking, timeout)

    def release(self):
        """
        Release the semaphore, incrementing the counter.

        Raises
        ------
        ValueError
            If released more times than acquired.
        """
        self._semaphore.release()

    def __enter__(self):
        """Enter the runtime context (acquire the semaphore)."""
        return self._semaphore.__enter__()

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit the runtime context (release the semaphore)."""
        return self._semaphore.__exit__(exc_type, exc_val, exc_tb)


class Condition:
    """
    Condition variable for worker coordination.

    A condition variable allows one or more workers to wait until notified by another
    worker. Uses :class:`threading.Condition` or :class:`multiprocessing.Condition`
    depending on backend.

    Parameters
    ----------
    lock : Lock or RLock, optional
        Underlying lock to use. If not provided, a new :class:`RLock` is created.

    See Also
    --------
    threading.Condition : :mod:`threading` implementation.
    multiprocessing.Condition : :mod:`multiprocessing` implementation.

    Examples
    --------
    .. code-block:: python

        from freethreading import Condition, Queue, Worker, current_worker

        def producer(condition, queue, data):
            with condition:
                queue.put(data)
                print(f"'{current_worker().name}' sent: {data}")
                condition.notify()

        def consumer(condition, queue):
            with condition:
                condition.wait()
                print(f"'{current_worker().name}' received: {queue.get()}")

        if __name__ == "__main__":
            condition = Condition()
            queue = Queue()
            c = Worker(name="Consumer", target=consumer, args=(condition, queue))
            p = Worker(name="Producer", target=producer, args=(condition, queue, 42))
            c.start()
            p.start()
            c.join()
            p.join()

    **Output**:

    .. code-block:: text

        'Producer' sent: 42
        'Consumer' received: 42
    """

    def __init__(self, lock=None):
        self._condition = _Condition(
            lock._lock if isinstance(lock, (Lock, RLock)) else None  # type: ignore[arg-type]
        )

    def __reduce__(self):
        if get_backend() == "threading":
            return (_raise_unpickle_type_error, ())
        return super().__reduce__()

    def acquire(self, blocking=True, timeout=None):
        """
        Acquire the underlying lock.

        Parameters
        ----------
        blocking : bool, default=True
            If True, block until the lock can be acquired. If False, return immediately.
        timeout : float, optional
            Maximum time to wait in seconds when blocking. None means wait forever.

        Returns
        -------
        bool
            True if acquired, False if not acquired (non-blocking or timeout).
        """
        if get_backend() == "threading":
            if timeout is None or timeout < 0:
                timeout = -1
        else:
            if timeout is not None and timeout < 0:
                timeout = None
        return self._condition.acquire(blocking, timeout)  # type: ignore[call-arg]

    def release(self):
        """
        Release the underlying lock.

        Raises
        ------
        RuntimeError
            When the lock is not held (threading backend).
        AssertionError
            When the lock is not held (multiprocessing backend).
        """
        self._condition.release()

    def wait(self, timeout=None):
        """
        Wait until notified or a timeout occurs.

        Parameters
        ----------
        timeout : float, optional
            Maximum time to wait in seconds. None means wait forever.

        Returns
        -------
        bool
            True if notified, False if timeout occurred.

        Raises
        ------
        RuntimeError
            When the lock is not held (threading backend).
        AssertionError
            When the lock is not held (multiprocessing backend).
        """
        return self._condition.wait(timeout)

    def wait_for(self, predicate, timeout=None):
        """
        Wait until a predicate becomes true.

        Parameters
        ----------
        predicate : callable
            Function that returns a boolean value.
        timeout : float, optional
            Maximum time to wait in seconds. None means wait forever.

        Returns
        -------
        bool
            The last value returned by the predicate.

        Raises
        ------
        RuntimeError
            When the lock is not held (threading backend).
        AssertionError
            When the lock is not held (multiprocessing backend).
        """
        return self._condition.wait_for(predicate, timeout)

    def notify(self, n=1):
        """
        Wake up one or more workers waiting on this condition.

        Parameters
        ----------
        n : int, default=1
            Number of workers to wake up.

        Raises
        ------
        RuntimeError
            When the lock is not held (threading backend).
        AssertionError
            When the lock is not held (multiprocessing backend).
        """
        self._condition.notify(n)

    def notify_all(self):
        """
        Wake up all workers waiting on this condition.

        Raises
        ------
        RuntimeError
            When the lock is not held (threading backend).
        AssertionError
            When the lock is not held (multiprocessing backend).
        """
        self._condition.notify_all()

    def __enter__(self):
        """Enter the runtime context (acquire the lock)."""
        return self._condition.__enter__()

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit the runtime context (release the lock)."""
        return self._condition.__exit__(exc_type, exc_val, exc_tb)


class Event:
    """
    Synchronization primitive for signaling between :class:`Worker` objects.

    An event manages an internal flag that can be set or cleared. Workers can
    wait for the flag to be set. Uses :class:`threading.Event` or
    :class:`multiprocessing.Event` depending on backend.

    See Also
    --------
    threading.Event : :mod:`threading` implementation.
    multiprocessing.Event : :mod:`multiprocessing` implementation.

    Examples
    --------
    .. code-block:: python

        from freethreading import Event, Worker, current_worker

        def wait(event):
            print(f"'{current_worker().name}': waiting for notification")
            event.wait()
            print(f"'{current_worker().name}': received notification")

        def notify(event):
            event.set()
            print(f"'{current_worker().name}': sent notification")

        if __name__ == "__main__":
            event = Event()
            waiter = Worker(name="Waiter", target=wait, args=(event,))
            notifier = Worker(name="Notifier", target=notify, args=(event,))
            waiter.start()
            notifier.start()
            waiter.join()
            notifier.join()

    **Output**:

    .. code-block:: text

        'Waiter': waiting for notification
        'Notifier': sent notification
        'Waiter': received notification
    """

    def __init__(self):
        self._event = _Event()

    def __reduce__(self):
        if get_backend() == "threading":
            return (_raise_unpickle_type_error, ())
        return super().__reduce__()

    def is_set(self):
        """
        Return True if and only if the internal flag is set.

        Returns
        -------
        bool
            True if set, False otherwise.
        """
        return self._event.is_set()

    def set(self):
        """Set the internal flag, waking up all waiting workers."""
        self._event.set()

    def clear(self):
        """Reset the internal flag to false."""
        self._event.clear()

    def wait(self, timeout=None):
        """
        Block until the internal flag is true.

        Parameters
        ----------
        timeout : float, optional
            Maximum time to wait in seconds. None means wait forever.

        Returns
        -------
        bool
            True if the flag is set, False if a timeout occurred.
        """
        return self._event.wait(timeout)


class Lock:
    """
    Mutual exclusion lock for worker synchronization.

    A lock ensures only one worker enters a critical section at a time. Uses
    :class:`threading.Lock` or :class:`multiprocessing.Lock` depending on backend.

    See Also
    --------
    threading.Lock : :mod:`threading` implementation.
    multiprocessing.Lock : :mod:`multiprocessing` implementation.

    Examples
    --------
    .. code-block:: python

        from freethreading import Lock, Worker, current_worker

        def critical(lock):
            with lock:
                print(f"'{current_worker().name}': acquired lock")

        if __name__ == "__main__":
            lock = Lock()
            workers = [
                Worker(name="Worker-1", target=critical, args=(lock,)),
                Worker(name="Worker-2", target=critical, args=(lock,)),
                Worker(name="Worker-3", target=critical, args=(lock,)),
            ]
            for w in workers:
                w.start()
            for w in workers:
                w.join()

    **Output**:

    .. code-block:: text

        'Worker-1': acquired lock
        'Worker-2': acquired lock
        'Worker-3': acquired lock
    """

    def __init__(self):
        self._lock = _Lock()

    def __reduce__(self):
        if get_backend() == "threading":
            return (_raise_unpickle_type_error, ())
        return super().__reduce__()

    def acquire(self, blocking=True, timeout=None):
        """
        Acquire the lock.

        Parameters
        ----------
        blocking : bool, default=True
            If True, block until the lock can be acquired. Otherwise, return
            immediately.
        timeout : float, optional
            Maximum time to wait in seconds when blocking. None means wait forever.

        Returns
        -------
        bool
            True if acquired, False if not acquired (non-blocking or timeout).
        """
        if get_backend() == "threading":
            if timeout is None or timeout < 0:
                timeout = -1
        else:
            if timeout is not None and timeout < 0:
                timeout = None
        return self._lock.acquire(blocking, timeout)  # type: ignore[call-arg]

    def release(self):
        """
        Release the lock.

        Raises
        ------
        RuntimeError
            When invoked on an unlocked lock (threading backend).
        ValueError
            When invoked on an unlocked lock (multiprocessing backend).
        """
        self._lock.release()

    def locked(self):
        """
        Return True if the lock is currently held.

        Returns
        -------
        bool
            True if locked, False otherwise.
        """
        if hasattr(self._lock, "locked"):
            return self._lock.locked()  # type: ignore[attr-defined]

        # Fallback for Python < 3.14
        if self.acquire(blocking=False):
            self.release()
            return False
        return True

    def __enter__(self):
        """Enter the runtime context (acquire the lock)."""
        return self._lock.__enter__()

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit the runtime context (release the lock)."""
        return self._lock.__exit__(exc_type, exc_val, exc_tb)


class Queue:
    """
    FIFO queue for worker communication.

    A queue supporting task tracking with :meth:`task_done` and :meth:`join`. Uses
    :class:`queue.Queue` or :class:`multiprocessing.JoinableQueue` depending on backend.

    Parameters
    ----------
    maxsize : int, default=0
        Maximum number of items allowed in the queue. 0 means unlimited.

    See Also
    --------
    queue.Queue : :mod:`threading` implementation.
    multiprocessing.JoinableQueue : :mod:`multiprocessing` implementation.

    Examples
    --------
    .. code-block:: python

        from freethreading import Queue, Worker

        def producer(queue):
            for value in range(3):
                print(f"Producing {value}")
                queue.put(value)
            queue.put(None)

        def consumer(queue):
            while True:
                item = queue.get()
                if item is None:
                    queue.task_done()
                    break
                print(f"Consuming {item}")
                queue.task_done()

        if __name__ == "__main__":
            queue = Queue()
            producer_worker = Worker(name="Producer", target=producer, args=(queue,))
            consumer_worker = Worker(name="Consumer", target=consumer, args=(queue,))
            producer_worker.start()
            consumer_worker.start()
            queue.join()
            producer_worker.join()
            consumer_worker.join()

    **Output**:

    .. code-block:: text

        Producing 0
        Producing 1
        Producing 2
        Consuming 0
        Consuming 1
        Consuming 2
    """

    def __init__(self, maxsize=0):
        self._queue = _Queue(maxsize)

    def __reduce__(self):
        if get_backend() == "threading":
            return (_raise_unpickle_type_error, ())
        return super().__reduce__()

    def put(self, item, block=True, timeout=None):
        """
        Put an item into the queue.

        Parameters
        ----------
        item
            Item to add to the queue.
        block : bool, default=True
            If True, block until space is available. Otherwise, return immediately.
        timeout : float, optional
            Maximum time to wait in seconds when blocking. None means wait forever.

        Raises
        ------
        queue.Full
            If the queue is full and non-blocking or timeout occurred.
        """
        self._queue.put(item, block=block, timeout=timeout)

    def get(self, block=True, timeout=None):
        """
        Remove and return an item from the queue.

        Parameters
        ----------
        block : bool, default=True
            If True, block until an item is available. Otherwise, return immediately.
        timeout : float, optional
            Maximum time to wait in seconds when blocking. None means wait forever.

        Returns
        -------
        item
            The next item from the queue.

        Raises
        ------
        queue.Empty
            If the queue is empty and non-blocking or timeout occurred.
        """
        return self._queue.get(block=block, timeout=timeout)

    def task_done(self):
        """
        Indicate that a formerly enqueued task is complete.

        Raises
        ------
        ValueError
            If called more times than there were items placed in the queue.
        """
        self._queue.task_done()

    def join(self):
        """Block until all items have been gotten and processed."""
        self._queue.join()

    def qsize(self):
        """
        Return the approximate size of the queue.

        Returns
        -------
        int
            Number of items in the queue.

        Raises
        ------
        NotImplementedError
            On macOS, due to platform limitations (sem_getvalue not implemented).
        """
        if sys.platform == "darwin":
            raise NotImplementedError(
                "qsize() is not available on macOS due to platform limitations."
            )
        return self._queue.qsize()

    def empty(self):
        """
        Return True if the queue is empty.

        Returns
        -------
        bool
            True if empty, False otherwise.
        """
        return self._queue.empty()

    def full(self):
        """
        Return True if the queue is full.

        Returns
        -------
        bool
            True if full, False otherwise.
        """
        return self._queue.full()

    def put_nowait(self, item):
        """
        Put an item into the queue without blocking.

        Parameters
        ----------
        item
            Item to add to the queue.

        Raises
        ------
        queue.Full
            If queue is full.
        """
        self._queue.put_nowait(item)

    def get_nowait(self):
        """
        Remove and return an item without blocking.

        Returns
        -------
        item
            The next item from the queue.

        Raises
        ------
        queue.Empty
            If queue is empty.
        """
        return self._queue.get_nowait()


class RLock:
    """
    Reentrant lock for worker synchronization.

    A reentrant lock can be acquired multiple times by the same worker without blocking.
    The lock must be released once for each time it was acquired. Uses
    :class:`threading.RLock` or :class:`multiprocessing.RLock` depending on backend.

    See Also
    --------
    threading.RLock : :mod:`threading` implementation.
    multiprocessing.RLock : :mod:`multiprocessing` implementation.

    Examples
    --------
    .. code-block:: python

        from freethreading import RLock, Worker, current_worker

        def countdown(rlock, n):
            with rlock:
                if n > 0:
                    print(f"'{current_worker().name}': {n}...")
                    countdown(rlock, n - 1)
                else:
                    print(f"'{current_worker().name}': go!")

        if __name__ == "__main__":
            rlock = RLock()
            worker = Worker(name="Worker-0", target=countdown, args=(rlock, 3))
            worker.start()
            worker.join()

    **Output**:

    .. code-block:: text

        'Worker-0': 3...
        'Worker-0': 2...
        'Worker-0': 1...
        'Worker-0': go!
    """

    def __init__(self):
        self._lock = _RLock()

    def __reduce__(self):
        if get_backend() == "threading":
            return (_raise_unpickle_type_error, ())
        return super().__reduce__()

    def acquire(self, blocking=True, timeout=None):
        """
        Acquire the lock, incrementing the recursion level.

        Parameters
        ----------
        blocking : bool, default=True
            If True, block until the lock can be acquired. Otherwise, return
            immediately.
        timeout : float, optional
            Maximum time to wait in seconds when blocking. None means wait forever.

        Returns
        -------
        bool
            True if acquired, False if not acquired (non-blocking or timeout).
        """
        if get_backend() == "threading":
            if timeout is None or timeout < 0:
                timeout = -1
        else:
            if timeout is not None and timeout < 0:
                timeout = None
        return self._lock.acquire(blocking, timeout)  # type: ignore[call-arg]

    def release(self):
        """
        Release the lock, decrementing the recursion level.

        Raises
        ------
        RuntimeError
            When invoked on an unlocked lock or by a worker other than the owner
            (threading backend).
        AssertionError
            When invoked on an unlocked lock or by a worker other than the owner
            (multiprocessing backend).
        """
        self._lock.release()

    def __enter__(self):
        """Enter the runtime context (acquire the lock)."""
        return self._lock.__enter__()

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit the runtime context (release the lock)."""
        return self._lock.__exit__(exc_type, exc_val, exc_tb)


class Semaphore:
    """
    Counting semaphore for limiting concurrent access.

    A semaphore manages an internal counter decremented by :meth:`acquire` calls
    and incremented by :meth:`release` calls. Uses :class:`threading.Semaphore`
    or :class:`multiprocessing.Semaphore` depending on backend.

    Parameters
    ----------
    value : int, default=1
        Initial value for the semaphore counter.

    See Also
    --------
    threading.Semaphore : :mod:`threading` implementation.
    multiprocessing.Semaphore : :mod:`multiprocessing` implementation.

    Examples
    --------
    .. code-block:: python

        from freethreading import Semaphore, Worker, current_worker

        def limited_resource(sem):
            with sem:
                print(f"'{current_worker().name}': in restricted section")

        if __name__ == "__main__":
            sem = Semaphore(1)
            workers = [
                Worker(name=f"Worker-{i}", target=limited_resource, args=(sem,))
                for i in range(3)
            ]
            for w in workers:
                w.start()
            for w in workers:
                w.join()

    **Output**:

    .. code-block:: text

        'Worker-0': in restricted section
        'Worker-1': in restricted section
        'Worker-2': in restricted section
    """

    def __init__(self, value=1):
        self._semaphore = _Semaphore(value)

    def __reduce__(self):
        if get_backend() == "threading":
            return (_raise_unpickle_type_error, ())
        return super().__reduce__()

    def acquire(self, blocking=True, timeout=None):
        """
        Acquire the semaphore, decrementing the counter.

        Parameters
        ----------
        blocking : bool, default=True
            If True, block until the semaphore can be acquired. Otherwise, return
            immediately.
        timeout : float, optional
            Maximum time to wait in seconds when blocking. None means wait forever.

        Returns
        -------
        bool
            True if acquired, False if not acquired (non-blocking or timeout).
        """
        return self._semaphore.acquire(blocking, timeout)

    def release(self):
        """Release the semaphore, incrementing the counter."""
        self._semaphore.release()

    def __enter__(self):
        """Enter the runtime context (acquire the semaphore)."""
        return self._semaphore.__enter__()

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit the runtime context (release the semaphore)."""
        return self._semaphore.__exit__(exc_type, exc_val, exc_tb)


class SimpleQueue:
    """
    Lightweight FIFO queue for worker communication.

    A simpler queue without task tracking or size limits. Uses
    :class:`queue.SimpleQueue` or :class:`multiprocessing.SimpleQueue` depending
    on backend.

    See Also
    --------
    queue.SimpleQueue : :mod:`threading` implementation.
    multiprocessing.SimpleQueue : :mod:`multiprocessing` implementation.

    Examples
    --------
    .. code-block:: python

        from freethreading import SimpleQueue, Worker

        def fill_queue(queue):
            queue.put("hello")
            queue.put("world")

        if __name__ == "__main__":
            queue = SimpleQueue()
            worker = Worker(target=fill_queue, args=(queue,))
            worker.start()
            print(queue.get())
            print(queue.get())
            worker.join()
            print(queue.empty())

    **Output**:

    .. code-block:: text

        hello
        world
        True
    """

    def __init__(self):
        self._queue = _SimpleQueue()

    def __reduce__(self):
        if get_backend() == "threading":
            return (_raise_unpickle_type_error, ())
        return super().__reduce__()

    def put(self, item):
        """
        Put an item into the queue.

        Parameters
        ----------
        item
            Item to add to the queue.

        Notes
        -----
        This method always blocks until the item can be added, ensuring
        consistent behavior across threading and multiprocessing backends.
        """
        self._queue.put(item)

    def get(self):
        """
        Remove and return an item from the queue.

        Returns
        -------
        item
            The next item from the queue.

        Notes
        -----
        This method always blocks until an item is available, ensuring
        consistent behavior across threading and multiprocessing backends.
        """
        return self._queue.get()

    def empty(self):
        """
        Return True if the queue is empty.

        Returns
        -------
        bool
            True if empty, False otherwise.
        """
        return self._queue.empty()


class Worker:
    """
    Thread or process for parallel execution.

    Represents an activity that runs in a separate thread or process. Uses
    :class:`threading.Thread` or :class:`multiprocessing.Process` depending on backend.

    Parameters
    ----------
    group : None
        Reserved for future extension (always None).
    target : callable, optional
        Function to be invoked by the :meth:`run` method.
    name : str, optional
        Worker name for identification.
    args : tuple, default=()
        Positional arguments for the target function.
    kwargs : dict, optional
        Keyword arguments for the target function.
    daemon : bool, optional
        Whether the worker is a daemon. Daemon workers are terminated when
        the program exits.

    Raises
    ------
    ValueError
        If target, args, or kwargs are not picklable. All arguments must be
        picklable to ensure portability across threading and multiprocessing
        backends. Use module-level functions instead of lambdas or nested
        functions.

    See Also
    --------
    threading.Thread : :mod:`threading` implementation.
    multiprocessing.Process : :mod:`multiprocessing` implementation.

    Examples
    --------
    .. code-block:: python

        from freethreading import Worker, current_worker

        def greet():
            print(f"Hello from {current_worker().name}!")

        if __name__ == "__main__":
            worker = Worker(name="Worker", target=greet)
            worker.start()
            worker.join()

    **Output**:

    .. code-block:: text

        Hello from Worker!
    """

    def __init__(
        self,
        group=None,
        target=None,
        name=None,
        args=(),
        kwargs=None,
        *,
        daemon=None,
    ):
        if kwargs is None:
            kwargs = {}

        _validate_picklability(target=target, args=args, kwargs=kwargs)

        self._worker = _Worker(
            group=group,
            target=target,
            name=name,
            args=args,
            kwargs=kwargs,
            daemon=daemon,
        )

    def start(self):
        """
        Start the worker's activity.

        Raises
        ------
        RuntimeError
            If called more than once (threading backend).
        AssertionError
            If called more than once (multiprocessing backend).
        """
        self._worker.start()

    def join(self, timeout=None):
        """
        Wait for the worker to terminate.

        Parameters
        ----------
        timeout : float, optional
            Maximum time to wait in seconds. None means wait forever.

        Raises
        ------
        RuntimeError
            If called before start or on the current worker (threading backend).
        AssertionError
            If called before start (multiprocessing backend).
        """
        self._worker.join(timeout)

    def is_alive(self):
        """
        Return whether the worker is alive.

        Returns
        -------
        bool
            True if the worker is still running.
        """
        return self._worker.is_alive()

    @property
    def name(self):
        """The worker's name."""
        return self._worker.name

    @name.setter
    def name(self, value):
        self._worker.name = value

    @property
    def daemon(self):
        """Whether the worker is a daemon."""
        return self._worker.daemon

    @daemon.setter
    def daemon(self, value):
        self._worker.daemon = value


class WorkerPool:
    """
    Pool of workers for parallel execution.

    Provides a pool of workers that can execute tasks in parallel. Uses
    :class:`multiprocessing.pool.Pool` or :class:`multiprocessing.pool.ThreadPool`
    depending on backend.

    Parameters
    ----------
    workers : int, optional
        Number of workers in the pool. Defaults to the number of CPUs.
    initializer : callable, optional
        Callable invoked on each worker at start.
    initargs : tuple, default=()
        Arguments for initializer.

    Raises
    ------
    ValueError
        If initializer or initargs are not picklable. All arguments must be picklable
        to ensure portability across threading and multiprocessing backends. Use
        module-level functions instead of lambdas or nested functions.

    See Also
    --------
    multiprocessing.pool.Pool : Process pool implementation.
    multiprocessing.pool.ThreadPool : Thread pool implementation.

    Examples
    --------
    .. code-block:: python

        from freethreading import WorkerPool

        def square(x):
            return x * x

        if __name__ == "__main__":
            with WorkerPool(workers=4) as pool:
                print(pool.map(square, range(10)))

    **Output**:

    .. code-block:: text

        [0, 1, 4, 9, 16, 25, 36, 49, 64, 81]
    """

    def __init__(self, workers=None, initializer=None, initargs=()):
        _validate_picklability(initializer=initializer, initargs=initargs)

        self._pool = _WorkerPool(
            processes=workers,
            initializer=initializer,
            initargs=initargs,
        )

    def apply(self, func, args=(), kwds=None):
        """
        Call func with arguments args and keyword arguments kwds.

        Blocks until the result is ready.

        Parameters
        ----------
        func : callable
            Function to call.
        args : tuple, default=()
            Positional arguments for func.
        kwds : dict, optional
            Keyword arguments for func.

        Returns
        -------
        object
            Result of the function call.

        Raises
        ------
        ValueError
            If func, args, or kwds are not picklable.
        """
        if kwds is None:
            kwds = {}
        _validate_picklability(func=func, args=args, kwds=kwds)
        return self._pool.apply(func, args, kwds)

    def apply_async(self, func, args=(), kwds=None, callback=None, error_callback=None):
        """
        Asynchronous version of :meth:`apply`.

        Parameters
        ----------
        func : callable
            Function to call.
        args : tuple, default=()
            Positional arguments for func.
        kwds : dict, optional
            Keyword arguments for func.
        callback : callable, optional
            Called with the result when ready.
        error_callback : callable, optional
            Called with exception if call fails.

        Returns
        -------
        AsyncResult
            Result object for retrieving the result.

        Raises
        ------
        ValueError
            If func, args, or kwds are not picklable.
        """
        if kwds is None:
            kwds = {}
        _validate_picklability(func=func, args=args, kwds=kwds)
        return self._pool.apply_async(
            func, args, kwds, callback=callback, error_callback=error_callback
        )

    def map(self, func, iterable, chunksize=None):
        """
        Apply func to each element in iterable.

        Blocks until all results are ready.

        Parameters
        ----------
        func : callable
            Function to apply.
        iterable : iterable
            Iterable of arguments.
        chunksize : int, optional
            Size of chunks for workers. Larger values reduce overhead.

        Returns
        -------
        list
            List of results in order.

        Raises
        ------
        ValueError
            If func is not picklable.
        """
        _validate_picklability(func=func)
        return self._pool.map(func, iterable, chunksize)

    def map_async(
        self, func, iterable, chunksize=None, callback=None, error_callback=None
    ):
        """
        Asynchronous version of :meth:`map`.

        Parameters
        ----------
        func : callable
            Function to apply.
        iterable : iterable
            Iterable of arguments.
        chunksize : int, optional
            Size of chunks for workers.
        callback : callable, optional
            Called with the result list when ready.
        error_callback : callable, optional
            Called with exception if call fails.

        Returns
        -------
        AsyncResult
            Result object for retrieving the results.

        Raises
        ------
        ValueError
            If func is not picklable.
        """
        _validate_picklability(func=func)
        return self._pool.map_async(
            func, iterable, chunksize, callback=callback, error_callback=error_callback
        )

    def imap(self, func, iterable, chunksize=1):
        """
        Lazier version of :meth:`map`.

        Parameters
        ----------
        func : callable
            Function to apply.
        iterable : iterable
            Iterable of arguments.
        chunksize : int, default=1
            Size of chunks for workers.

        Returns
        -------
        iterator
            Iterator yielding results in order.

        Raises
        ------
        ValueError
            If func is not picklable.
        """
        _validate_picklability(func=func)
        return self._pool.imap(func, iterable, chunksize)

    def imap_unordered(self, func, iterable, chunksize=1):
        """
        Like :meth:`imap` but results are yielded as soon as ready.

        Parameters
        ----------
        func : callable
            Function to apply.
        iterable : iterable
            Iterable of arguments.
        chunksize : int, default=1
            Size of chunks for workers.

        Returns
        -------
        iterator
            Iterator yielding results as they complete.

        Raises
        ------
        ValueError
            If func is not picklable.
        """
        _validate_picklability(func=func)
        return self._pool.imap_unordered(func, iterable, chunksize)

    def starmap(self, func, iterable, chunksize=None):
        """
        Like :meth:`map` but arguments are unpacked from iterables.

        Parameters
        ----------
        func : callable
            Function to apply.
        iterable : iterable
            Iterable of argument tuples.
        chunksize : int, optional
            Size of chunks for workers.

        Returns
        -------
        list
            List of results in order.

        Raises
        ------
        ValueError
            If func is not picklable.
        """
        _validate_picklability(func=func)
        return self._pool.starmap(func, iterable, chunksize)

    def starmap_async(
        self, func, iterable, chunksize=None, callback=None, error_callback=None
    ):
        """
        Asynchronous version of :meth:`starmap`.

        Parameters
        ----------
        func : callable
            Function to apply.
        iterable : iterable
            Iterable of argument tuples.
        chunksize : int, optional
            Size of chunks for workers.
        callback : callable, optional
            Called with the result list when ready.
        error_callback : callable, optional
            Called with exception if call fails.

        Returns
        -------
        AsyncResult
            Result object for retrieving the results.

        Raises
        ------
        ValueError
            If func is not picklable.
        """
        _validate_picklability(func=func)
        return self._pool.starmap_async(
            func, iterable, chunksize, callback=callback, error_callback=error_callback
        )

    def close(self):
        """
        Prevent any more tasks from being submitted to the pool.

        Once all tasks are complete, workers will exit.
        """
        self._pool.close()

    def terminate(self):
        """
        Stop workers immediately without completing outstanding work.
        """
        self._pool.terminate()

    def join(self):
        """
        Wait for workers to exit.

        Must call :meth:`close` or :meth:`terminate` before using :meth:`join`.
        """
        self._pool.join()

    def __enter__(self):
        """Enter the runtime context."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit the runtime context (terminate the pool)."""
        self.terminate()
        return False


class WorkerPoolExecutor:
    """
    Executor that manages a pool of :class:`Worker` objects.

    Provides a high-level interface for asynchronously executing callables using
    a pool of workers. Uses :class:`concurrent.futures.ThreadPoolExecutor` or
    :class:`concurrent.futures.ProcessPoolExecutor` depending on backend.

    Parameters
    ----------
    max_workers : int, optional
        Maximum number of workers in the pool.
    initializer : callable, optional
        A callable used to initialize worker threads or processes.
    initargs : tuple, optional
        A tuple of arguments to pass to the initializer.
    **kwargs
        Additional arguments passed to the underlying executor.

    See Also
    --------
    concurrent.futures.ThreadPoolExecutor : Thread pool executor.
    concurrent.futures.ProcessPoolExecutor : Process pool executor.

    Examples
    --------
    .. code-block:: python

        from freethreading import WorkerPoolExecutor

        def square(x):
            return x * x

        if __name__ == "__main__":
            with WorkerPoolExecutor(max_workers=4) as executor:
                results = list(executor.map(square, range(10)))
            print(results)

    **Output**:

    .. code-block:: text

        [0, 1, 4, 9, 16, 25, 36, 49, 64, 81]
    """

    def __init__(self, max_workers=None, initializer=None, initargs=(), **kwargs):
        if get_backend() == "multiprocessing":
            kwargs["mp_context"] = _get_mp_context()
        self._executor = _WorkerPoolExecutor(
            max_workers=max_workers,
            initializer=initializer,
            initargs=initargs,
            **kwargs,
        )

    def submit(self, fn, *args, **kwargs):
        """
        Submit a callable to be executed.

        Parameters
        ----------
        fn : callable
            The callable to execute.
        *args
            Positional arguments for fn.
        **kwargs
            Keyword arguments for fn.

        Returns
        -------
        Future
            A Future representing the execution.

        Raises
        ------
        ValueError
            If fn, args, or kwargs are not picklable.
        """
        _validate_picklability(fn=fn, args=args, kwargs=kwargs)
        return self._executor.submit(fn, *args, **kwargs)

    def map(self, fn, *iterables, timeout=None, chunksize=1):
        """
        Map a function over iterables.

        Parameters
        ----------
        fn : callable
            Function to apply.
        *iterables
            Iterables to map over.
        timeout : float, optional
            Maximum time to wait for results. None means no limit.
        chunksize : int, default=1
            Size of chunks for workers.

        Returns
        -------
        iterator
            Iterator over results.

        Raises
        ------
        ValueError
            If fn is not picklable.
        TimeoutError
            If the entire result iterator could not be generated before the timeout.
        """
        _validate_picklability(fn=fn)
        return self._executor.map(fn, *iterables, timeout=timeout, chunksize=chunksize)

    def shutdown(self, wait=True, cancel_futures=False):
        """
        Shutdown the executor.

        Parameters
        ----------
        wait : bool, default=True
            If True, wait for pending futures to complete.
        cancel_futures : bool, default=False
            If True, cancel pending futures.
        """
        return self._executor.shutdown(wait=wait, cancel_futures=cancel_futures)

    def __enter__(self):
        """Enter the runtime context."""
        return self._executor.__enter__()

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit the runtime context (shutdown the executor)."""
        return self._executor.__exit__(exc_type, exc_val, exc_tb)


def _raise_unpickle_type_error():
    raise TypeError("Cannot unpickle freethreading primitives on threading backend")


def _validate_picklability(**kwargs):
    """Validate that all arguments are picklable for multiprocessing compatibility."""
    spawning_popen = get_spawning_popen()
    set_spawning_popen(_DummyPopen)
    try:
        dump(tuple(kwargs.values()), io.BytesIO())
    except (AttributeError, TypeError, pickle.PicklingError) as e:
        raise ValueError(
            f"{list(kwargs.keys())} must be picklable for compatibility with "
            f"multiprocessing backend. Error: {e}. "
            f"Use module-level functions instead of lambdas or nested functions."
        ) from e
    finally:
        set_spawning_popen(spawning_popen)


def active_children() -> list[Thread] | list[BaseProcess]:
    """
    Return a list of all active workers, excluding the current one.

    Returns
    -------
    list of Thread | BaseProcess
        List of child thread or process objects currently alive, excluding the
        current worker.

    See Also
    --------
    active_count : Get the count of all active workers
    current_worker : Get the current worker
    enumerate : Get a list of all workers

    Examples
    --------
    .. code-block:: python

        from freethreading import Worker, active_children

        def busy_wait():
            while True:
                pass

        if __name__ == "__main__":
            daemon = Worker(target=busy_wait, name="Daemon", daemon=True)
            daemon.start()
            print([child.name for child in active_children()])

    **Output**:

    .. code-block:: text

        ['Daemon']
    """
    return _active_children()


def active_count() -> int:
    """
    Return the number of currently active workers.

    Returns
    -------
    int
        Number of currently running workers.

    See Also
    --------
    current_worker : Get the current worker
    enumerate : Get a list of all workers

    Notes
    -----
    This counts all workers (threads or processes) that have been started but not yet
    finished.

    Examples
    --------
    .. code-block:: python

        from freethreading import Worker, active_count

        def busy_wait():
            while True:
                pass

        if __name__ == "__main__":
            daemon = Worker(target=busy_wait, daemon=True)
            daemon.start()
            print(active_count())  # Should print 2 (main worker + daemon worker)

    **Output**:

    .. code-block:: text

        2
    """
    return _active_count()


def current_worker() -> Thread | BaseProcess:
    """
    Return the current worker object.

    Returns
    -------
    Thread | BaseProcess
        The underlying thread or process object corresponding to the caller.

    See Also
    --------
    active_count : Get the count of all active workers
    get_ident : Get the identifier of the current worker

    Examples
    --------
    .. code-block:: python

        from freethreading import current_worker

        print(current_worker().name)

    **Output (Standard Python)**:

    .. code-block:: text

        MainProcess

    **Output (Free-threaded Python)**:

    .. code-block:: text

        MainThread
    """
    return _current_worker()


def enumerate() -> list[Thread] | list[BaseProcess]:
    """
    Return a list of all active worker objects, including the current one.

    Returns
    -------
    list of Thread | BaseProcess
        List of all underlying thread or process objects currently alive,
        including the current worker.

    See Also
    --------
    current_worker : Get the current worker
    active_children : Get a list of all workers, excluding the current one
    active_count : Get the count of all active workers

    Notes
    -----
    Backend-specific attributes like ``pid`` (processes) or ``native_id`` (threads)
    are also available but not portable across backends.

    Examples
    --------
    .. code-block:: python

        from freethreading import Worker, enumerate

        def busy_wait():
            while True:
                pass

        if __name__ == "__main__":
            daemon = Worker(target=busy_wait, name="Daemon", daemon=True)
            daemon.start()
            print([worker.name for worker in enumerate()])

    **Output (Standard Python)**:

    .. code-block:: text

        ['Daemon', 'MainProcess']

    **Output (Free-threaded Python)**:

    .. code-block:: text

        ['MainThread', 'Daemon']
    """
    return _enumerate()


def get_ident() -> int:
    """
    Return the identifier of the current worker.

    Returns
    -------
    int
        Thread identifier or process ID of the current worker.

    See Also
    --------
    current_worker : Get the current worker
    """
    return _get_ident()


__all__ = [
    "Barrier",
    "BoundedSemaphore",
    "Condition",
    "Event",
    "Lock",
    "Queue",
    "RLock",
    "Semaphore",
    "SimpleQueue",
    "Worker",
    "WorkerPool",
    "WorkerPoolExecutor",
    "active_children",
    "active_count",
    "current_worker",
    "enumerate",
    "get_backend",
    "get_ident",
]
