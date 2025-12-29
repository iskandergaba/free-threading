"""Tests for freethreading module on both threading and multiprocessing backends."""

import importlib
import platform
import sys
import threading
import time

import pytest


# Module-level functions for multiprocessing picklability
def task():
    pass


def task_with_kwargs(x, y=10):
    return x + y


def task_with_args(x):
    return x * x


@pytest.fixture(params=[True, False], ids=["multiprocessing", "threading"])
def backend(request, monkeypatch):
    """Fixture that tests both backends by mocking GIL status."""
    monkeypatch.setattr(sys, "_is_gil_enabled", lambda: request.param, raising=False)
    import freethreading

    return importlib.reload(freethreading)


def test_barrier_wait(backend):
    barrier = backend.Barrier(1)
    result = barrier.wait()
    assert result == 0


def test_barrier_wait_timeout(backend):
    barrier = backend.Barrier(2)
    timeout_raised = False

    try:
        barrier.wait(timeout=0.01)
    except threading.BrokenBarrierError:
        timeout_raised = True

    assert timeout_raised


def test_barrier_reset(backend):
    barrier = backend.Barrier(1)
    barrier.wait()
    barrier.reset()
    result = barrier.wait()
    assert result == 0


def test_barrier_abort(backend):
    barrier = backend.Barrier(2)
    barrier.abort()
    assert barrier.broken


def test_barrier_properties(backend):
    barrier = backend.Barrier(3)

    assert barrier.parties == 3
    assert barrier.n_waiting == 0
    assert not barrier.broken


def test_bounded_semaphore_acquire_release(backend):
    sem = backend.BoundedSemaphore(2)
    assert sem.acquire()
    sem.release()


def test_bounded_semaphore_context_manager_exception(backend):
    sem = backend.BoundedSemaphore(1)
    try:
        with sem:
            raise ValueError("test")
    except ValueError:
        pass
    assert not sem.acquire(blocking=False) or sem.release() is None


def test_condition_no_lock(backend):
    cond = backend.Condition()
    with cond:
        assert cond is not None


def test_condition_with_lock(backend):
    lock = backend.Lock()
    cond = backend.Condition(lock)
    with cond:
        assert cond is not None


def test_condition_with_rlock(backend):
    rlock = backend.RLock()
    cond = backend.Condition(rlock)
    with cond:
        with cond:
            assert cond is not None


def test_condition_acquire_release(backend):
    cond = backend.Condition()
    acquired = cond.acquire()
    assert acquired is True
    cond.release()


def test_condition_acquire_negative_timeout(backend):
    cond = backend.Condition()
    result = cond.acquire(blocking=True, timeout=-0.5)
    assert result
    cond.release()


def test_condition_context_manager(backend):
    cond = backend.Condition()
    with cond:
        assert cond is not None


def test_condition_context_manager_exception(backend):
    cond = backend.Condition()
    exception_raised = False
    try:
        with cond:
            raise ValueError("test")
    except ValueError:
        exception_raised = True
    assert exception_raised
    assert cond.acquire()
    cond.release()


def test_condition_wait(backend):
    cond = backend.Condition()
    error_raised = False
    try:
        with cond:
            cond.wait(timeout=0.01)
    except Exception:
        error_raised = True
    assert not error_raised


def test_condition_wait_for(backend):
    cond = backend.Condition()
    flag = []

    def predicate():
        return len(flag) > 0

    flag.append(1)

    with cond:
        result = cond.wait_for(predicate, timeout=0.01)
        assert result


def test_condition_notify_with_count(backend):
    cond = backend.Condition()
    assert cond.acquire()
    cond.notify(0)
    cond.notify(10)
    cond.release()
    assert cond.acquire()
    cond.release()


def test_condition_notify_all(backend):
    cond = backend.Condition()
    with cond:
        cond.notify_all()


def test_event_is_set(backend):
    event = backend.Event()
    assert not event.is_set()

    event.set()
    assert event.is_set()

    event.clear()
    assert not event.is_set()


def test_event_wait(backend):
    event = backend.Event()

    # Wait on unset event should timeout
    result = event.wait(timeout=0.01)
    assert not result

    # Wait on set event should return immediately
    event.set()
    result = event.wait(timeout=0.01)
    assert result


def test_lock_acquire_release(backend):
    lock = backend.Lock()
    assert lock.acquire()
    lock.release()


def test_lock_context_manager(backend):
    lock = backend.Lock()
    assert not lock.locked()

    with lock:
        assert lock.locked()

    assert not lock.locked()


def test_lock_acquire_timeout(backend):
    lock = backend.Lock()

    acquired = lock.acquire(timeout=0.01)
    assert acquired

    acquired2 = lock.acquire(blocking=False)
    assert not acquired2

    lock.release()


def test_lock_acquire_negative_timeout(backend):
    lock = backend.Lock()
    result = lock.acquire(blocking=True, timeout=-1)
    assert result
    lock.release()


def test_queue_put_get(backend):
    q = backend.Queue()
    q.put(42)
    result = q.get()
    assert result == 42


def test_queue_multiple_items(backend):
    q = backend.Queue()

    for i in range(5):
        q.put(i)

    results = []
    for _ in range(5):
        results.append(q.get())

    assert results == [0, 1, 2, 3, 4]


def test_queue_nowait_methods(backend):
    import queue

    q = backend.Queue()

    q.put_nowait(42)

    if backend.get_backend() == "multiprocessing":
        time.sleep(0.01)

    result = q.get_nowait()
    assert result == 42

    try:
        q.get_nowait()
        assert False, "Should have raised Empty"
    except queue.Empty:
        pass


def test_queue_task_done_join(backend):
    q = backend.Queue()
    error_raised = False

    try:
        q.put(1)
        q.put(2)

        q.get()
        q.task_done()
        q.get()
        q.task_done()

        q.join()
    except Exception:
        error_raised = True

    assert not error_raised


def test_queue_qsize(backend):
    q = backend.Queue()

    # qsize() raises NotImplementedError on macOS due to platform limitations
    if platform.system() == "Darwin":
        with pytest.raises(NotImplementedError):
            q.qsize()
        return

    assert q.qsize() == 0
    q.put(1)

    if backend.get_backend() == "multiprocessing":
        time.sleep(0.01)

    assert q.qsize() == 1
    q.get()
    assert q.qsize() == 0


def test_queue_empty_full(backend):
    q = backend.Queue(maxsize=2)

    assert q.empty()
    assert not q.full()

    q.put(1)

    if backend.get_backend() == "multiprocessing":
        time.sleep(0.01)

    assert not q.empty()
    assert not q.full()

    q.put(2)

    if backend.get_backend() == "multiprocessing":
        time.sleep(0.01)

    assert not q.empty()
    assert q.full()

    q.get()
    q.get()
    assert q.empty()


def test_rlock_acquire_release(backend):
    lock = backend.RLock()
    assert lock.acquire()
    assert lock.acquire()
    lock.release()
    lock.release()


def test_rlock_acquire_negative_timeout(backend):
    lock = backend.RLock()
    result = lock.acquire(blocking=True, timeout=-0.5)
    assert result
    lock.release()


def test_rlock_context_manager(backend):
    lock = backend.RLock()
    with lock:
        with lock:
            assert lock is not None


def test_semaphore_acquire_release(backend):
    sem = backend.Semaphore(2)
    assert sem.acquire()
    sem.release()


def test_semaphore_context_manager_exception(backend):
    sem = backend.Semaphore(1)
    try:
        with sem:
            raise ValueError("test")
    except ValueError:
        pass
    assert not sem.acquire(blocking=False) or sem.release() is None


def test_semaphore_timeout(backend):
    sem = backend.Semaphore(1)

    acquired = sem.acquire(timeout=0.01)
    assert acquired

    acquired2 = sem.acquire(blocking=False)
    assert not acquired2

    sem.release()


def test_simple_queue_put_get(backend):
    q = backend.SimpleQueue()
    q.put(42)
    result = q.get()
    assert result == 42


def test_simple_queue_empty(backend):
    q = backend.SimpleQueue()

    assert q.empty()

    q.put(42)
    assert not q.empty()

    q.get()
    assert q.empty()


def test_worker_with_args(backend):
    worker = backend.Worker(target=task_with_args, args=(1,))
    assert worker is not None
    worker.start()
    worker.join()


def test_worker_with_kwargs(backend):
    worker = backend.Worker(target=task_with_kwargs, kwargs={"x": 5, "y": 15})
    assert worker is not None
    worker.start()
    worker.join()


def test_worker_name_property(backend):
    worker = backend.Worker(target=task, name="InitialName")
    assert worker.name == "InitialName"

    # Set new name before starting
    worker.name = "NewName"
    assert worker.name == "NewName"

    worker.start()
    worker.join()


def test_worker_daemon_property(backend):
    worker = backend.Worker(target=task, daemon=False)
    assert worker.daemon is False

    worker.daemon = True
    assert worker.daemon is True

    worker.start()
    worker.join()


@pytest.mark.flaky(reruns=3)
def test_worker_is_alive(backend):
    worker = backend.Worker(target=time.sleep, args=(0.1,))
    assert not worker.is_alive()

    worker.start()
    assert worker.is_alive()

    worker.join()
    assert not worker.is_alive()


@pytest.mark.flaky(reruns=3)
def test_worker_join_timeout(backend):
    worker = backend.Worker(target=time.sleep, args=(0.1,))
    worker.start()

    # Join with short timeout should not wait for completion
    worker.join(timeout=0.001)
    assert worker.is_alive()

    # Join without timeout should wait
    worker.join()
    assert not worker.is_alive()


def test_worker_pickling_exception(backend):
    with pytest.raises(ValueError, match="must be picklable"):
        backend.Worker(target=lambda: None)


@pytest.mark.flaky(reruns=3)
def test_worker_pool_apply(backend):
    with backend.WorkerPool(workers=2) as pool:
        result = pool.apply(task_with_args, (5,))

    assert result == 25


def test_worker_pool_apply_with_kwds(backend):
    with backend.WorkerPool(workers=2) as pool:
        result = pool.apply(task_with_kwargs, (5,), {"y": 3})

    assert result == 8


@pytest.mark.flaky(reruns=3)
def test_worker_pool_apply_async(backend):
    with backend.WorkerPool(workers=2) as pool:
        async_result = pool.apply_async(task_with_args, (7,))
        result = async_result.get(timeout=5)

    assert result == 49


def test_worker_pool_apply_async_callback(backend):
    results = []

    def callback(result):
        results.append(result)

    with backend.WorkerPool(workers=2) as pool:
        async_result = pool.apply_async(task_with_args, (6,), callback=callback)
        async_result.wait(timeout=5)

    time.sleep(0.1)  # Give callback time to execute
    assert 36 in results


def test_worker_pool_map(backend):
    with backend.WorkerPool(workers=2) as pool:
        results = pool.map(task_with_args, [1, 2, 3, 4])

    assert results == [1, 4, 9, 16]


def test_worker_pool_map_chunksize(backend):
    with backend.WorkerPool(workers=2) as pool:
        results = pool.map(task_with_args, range(10), chunksize=3)

    assert results == [0, 1, 4, 9, 16, 25, 36, 49, 64, 81]


@pytest.mark.flaky(reruns=3)
def test_worker_pool_map_async(backend):
    with backend.WorkerPool(workers=2) as pool:
        async_result = pool.map_async(task_with_args, [1, 2, 3, 4])
        results = async_result.get(timeout=5)

    assert results == [1, 4, 9, 16]


def test_worker_pool_imap(backend):
    with backend.WorkerPool(workers=2) as pool:
        results = list(pool.imap(task_with_args, [1, 2, 3, 4]))

    assert results == [1, 4, 9, 16]


def test_worker_pool_imap_unordered(backend):
    with backend.WorkerPool(workers=2) as pool:
        results = sorted(pool.imap_unordered(task_with_args, [1, 2, 3, 4]))

    assert results == [1, 4, 9, 16]


def test_worker_pool_starmap(backend):
    with backend.WorkerPool(workers=2) as pool:
        results = pool.starmap(task_with_args, [(1,), (2,), (3,), (4,)])

    assert results == [1, 4, 9, 16]


def test_worker_pool_starmap_async(backend):
    with backend.WorkerPool(workers=2) as pool:
        async_result = pool.starmap_async(task_with_args, [(1,), (2,), (3,), (4,)])
        results = async_result.get(timeout=5)

    assert results == [1, 4, 9, 16]


def test_worker_pool_close_join(backend):
    pool = backend.WorkerPool(workers=2)
    async_result = pool.apply_async(task_with_args, (5,))

    pool.close()
    pool.join()

    assert async_result.get(timeout=1) == 25


def test_worker_pool_terminate(backend):
    pool = backend.WorkerPool(workers=2)
    pool.terminate()
    pool.join()


def test_worker_pool_pickling_exception(backend):
    with pytest.raises(ValueError, match="must be picklable"):
        backend.WorkerPool(initializer=lambda: None)


@pytest.mark.flaky(reruns=3)
def test_worker_pool_executor_map(backend):
    with backend.WorkerPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(task_with_args, [1, 2, 3, 4]))

    assert results == [1, 4, 9, 16]


def test_worker_pool_executor_submit(backend):
    with backend.WorkerPoolExecutor(max_workers=2) as executor:
        future = executor.submit(task_with_args, 5)
        result = future.result()

    assert result == 25


def test_worker_pool_executor_shutdown(backend):
    executor = backend.WorkerPoolExecutor(max_workers=2)

    # Submit a task
    future = executor.submit(task_with_args, 3)
    result = future.result()
    assert result == 9

    # Shutdown
    executor.shutdown(wait=True)

    # Cannot submit after shutdown
    try:
        executor.submit(task_with_args, 4)
        assert False, "Should not be able to submit after shutdown"
    except RuntimeError:
        pass


def test_active_children(backend):
    initial_children = backend.active_children()

    worker = backend.Worker(target=time.sleep, args=(0.1,))
    worker.start()

    children = backend.active_children()
    assert len(children) >= len(initial_children)

    worker.join()


def test_active_count(backend):
    count = backend.active_count()
    assert isinstance(count, int)
    assert count >= 0


def test_current_worker(backend):
    worker = backend.current_worker()
    assert worker is not None


def test_enumerate(backend):
    workers = backend.enumerate()
    assert isinstance(workers, list)


def test_get_backend(backend):
    result = backend.get_backend()
    assert result in ["threading", "multiprocessing"]


def test_get_ident(backend):
    ident = backend.get_ident()
    assert isinstance(ident, int)
    assert ident > 0
