Usage Guide
===========

Overview
--------

:mod:`freethreading` shields you from differences between GIL-enabled Python builds and free-threaded builds. At import
time it decides whether to route calls through :mod:`multiprocessing` (GIL-enabled Python) or :mod:`threading`
(GIL-disabled Python). The public surface mirrors the common subset shared by both backends, so you can write portable
code once and run it efficiently everywhere.

Parallel Execution
------------------

:mod:`freethreading` offers low-level :class:`~freethreading.Worker` objects for direct task control,
:class:`~freethreading.WorkerPool` objects for pool-based parallelism, and high-level
:class:`~freethreading.WorkerPoolExecutor` objects for managed execution.

``Worker``
^^^^^^^^^^

The :class:`~freethreading.Worker` class represents an activity that is run in a separate thread or process. It is a
wrapper that carries over the shared controls from :class:`~threading.Thread` and :class:`~multiprocessing.Process`, so
that you can name workers, set :attr:`~freethreading.Worker.daemon`, and call familiar methods like
:meth:`~freethreading.Worker.start()`, :meth:`~freethreading.Worker.join()`, and
:meth:`~freethreading.Worker.is_alive()`, without worrying about the underlying implementation. Here's a quick example:

.. code-block:: python

    from freethreading import Worker, current_worker

    def greet():
        print(f"Hello from {current_worker().name}!")

    if __name__ == "__main__":
        worker = Worker(name="Worker", target=greet, daemon=False)
        worker.start()
        worker.join()

**Output**:

.. code-block:: text

    Hello from Worker!

``WorkerPool``
^^^^^^^^^^^^^^

:class:`~freethreading.WorkerPool` wraps :class:`~multiprocessing.pool.Pool` and
:class:`~multiprocessing.pool.ThreadPool` into a single interface. Here's an example of how to use it:

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

``WorkerPoolExecutor``
^^^^^^^^^^^^^^^^^^^^^^

:class:`~freethreading.WorkerPoolExecutor` provides a unified drop-in replacement for
:class:`~concurrent.futures.ThreadPoolExecutor` and :class:`~concurrent.futures.ProcessPoolExecutor`. For instance:

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


Data Exchange
-------------

Workers can exchange data through :class:`~freethreading.Queue` for structured coordination or
:class:`~freethreading.SimpleQueue` for lightweight messaging.

``Queue``
^^^^^^^^^

:class:`freethreading.Queue` wraps :class:`queue.Queue` and :class:`multiprocessing.JoinableQueue` into a single
interface that behaves identically on both :mod:`threading` and :mod:`multiprocessing` backends. As an example:

.. code-block:: python

    from freethreading import Queue, Worker

    def producer(queue):
        for value in range(3):
            print(f"Producing {value}")
            queue.put(value)
        queue.put(None)  # Sentinel marks completion

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


``SimpleQueue``
^^^^^^^^^^^^^^^

Similarly, :class:`freethreading.SimpleQueue` wraps the unbounded, lightweight :class:`queue.SimpleQueue` and
:class:`multiprocessing.SimpleQueue` into a single interface that behaves identically on both backends. For example:

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


Synchronization Primitives
--------------------------

:mod:`freethreading` offers the synchronization primitives common to :mod:`threading` and :mod:`multiprocessing`,
enabling worker coordination and control of shared resources. Below are examples of how to use them.

Locks and Reentrant Locks
^^^^^^^^^^^^^^^^^^^^^^^^^

:class:`~freethreading.Lock` and :class:`~freethreading.RLock` wrap the lock types found in :mod:`threading` and
:mod:`multiprocessing`. A lock ensures only one worker enters a critical section at a time, and a reentrant lock allows
the same worker to acquire it multiple times without deadlocking. Here's how they work:

.. code-block:: python

    from freethreading import Lock, RLock, Worker, current_worker

    def critical(lock):
        with lock:
            print(f"'{current_worker().name}' acquired the lock")

    def countdown(rlock, n):
        with rlock:
            if n > 0:
                print(f"'{current_worker().name}': {n}...")
                countdown(rlock, n - 1)
            else:
                print(f"'{current_worker().name}': go!")

    if __name__ == "__main__":
        lock = Lock()
        workers = [
            Worker(name=f"Worker-{i}", target=critical, args=(lock,)) for i in range(2)
        ]
        for w in workers:
            w.start()
        for w in workers:
            w.join()

        print()

        rlock = RLock()
        workers = [
            Worker(name=f"Worker-{i}", target=countdown, args=(rlock, 3)) for i in range(2)
        ]
        for w in workers:
            w.start()
        for w in workers:
            w.join()

**Output**:

.. code-block:: text

   'Worker-0' acquired the lock
   'Worker-1' acquired the lock

   'Worker-0': 3...
   'Worker-0': 2...
   'Worker-0': 1...
   'Worker-0': go!
   'Worker-1': 3...
   'Worker-1': 2...
   'Worker-1': 1...
   'Worker-1': go!


Semaphores and Conditions
^^^^^^^^^^^^^^^^^^^^^^^^^

:class:`~freethreading.Semaphore`, :class:`~freethreading.BoundedSemaphore`, and :class:`~freethreading.Condition`
provide wrappers over their :mod:`threading` and :mod:`multiprocessing` equivalents. Semaphores control how many
workers can access a resource at once, and conditions allow workers to wait until notified. The example below puts all
of them to work:


.. code-block:: python

    from freethreading import Condition, Queue, Semaphore, Worker, current_worker

    def restricted(semaphore):
        with semaphore:
            print(f"'{current_worker().name}' in restricted section")

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
        semaphore = Semaphore(2)
        workers = [
            Worker(name=f"Worker-{i}", target=restricted, args=(semaphore,))
            for i in range(3)
        ]
        for w in workers:
            w.start()
        for w in workers:
            w.join()

        print()

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

   'Worker-0' in restricted section
   'Worker-1' in restricted section
   'Worker-2' in restricted section

   'Producer' sent: 42
   'Consumer' received: 42


:class:`~freethreading.BoundedSemaphore` behaves like :class:`~freethreading.Semaphore` but prevents over-releasing by
raising :exc:`ValueError` if :meth:`~freethreading.BoundedSemaphore.release` is called more times than
:meth:`~freethreading.BoundedSemaphore.acquire`. The following example shows the difference:

.. code-block:: python

   from freethreading import Semaphore, BoundedSemaphore

   s = Semaphore(1)
   s.acquire()  # Decreases counter to 0
   s.release()  # Increases counter to 1
   s.release()  # Increases counter to 2

   b = BoundedSemaphore(1)
   b.acquire()  # Decreases counter to 0
   b.release()  # Increases counter to 1
   b.release()  # Raises ValueError

**Output**:

.. code-block:: text

   Traceback (most recent call last):
       ...
   ValueError: Semaphore released too many times


Events and Barriers
^^^^^^^^^^^^^^^^^^^

:class:`~freethreading.Event` and :class:`~freethreading.Barrier` wrap their :mod:`threading` and
:mod:`multiprocessing` counterparts. Events broadcast a signal that unblocks waiting workers, while barriers hold
workers until a fixed number have arrived. Below is a quick example:

.. code-block:: python

    from freethreading import Barrier, Event, Worker, current_worker

    def runner(start_signal, checkpoint):
        print(f"'{current_worker().name}' waiting for start signal")
        start_signal.wait()  # All runners wait for the event
        print(f"'{current_worker().name}' started")
        checkpoint.wait()  # Synchronize at the checkpoint
        print(f"'{current_worker().name}' passed checkpoint")

    if __name__ == "__main__":
        start_signal = Event()
        checkpoint = Barrier(3)
        workers = [
            Worker(name=f"Runner-{i}", target=runner, args=(start_signal, checkpoint))
            for i in range(3)
        ]
        for w in workers:
            w.start()

        # Give workers time to reach wait state, then signal
        start_signal.set()

        for w in workers:
            w.join()

**Output**:

.. code-block:: text

    'Runner-0' waiting for start signal
    'Runner-1' waiting for start signal
    'Runner-2' waiting for start signal
    'Runner-2' started
    'Runner-0' started
    'Runner-1' started
    'Runner-1' passed checkpoint
    'Runner-0' passed checkpoint
    'Runner-2' passed checkpoint


Utility Functions
-----------------

:mod:`freethreading` provides a collection of commonly used functions from both :mod:`threading` and
:mod:`multiprocessing`. Here's a quick overview example of how to use them:

.. code-block:: python

    from freethreading import (
        Worker,
        active_children,
        active_count,
        current_worker,
        enumerate,
        get_ident,
    )

    def busy_wait():
        while True:
            pass

    if __name__ == "__main__":
        Worker(target=busy_wait, name="Daemon", daemon=True).start()

        # MainThread or MainProcess
        print(current_worker().name)

        # Thread or process identifier
        print(get_ident())

        # Number of active workers
        print(active_count())

        # List all active workers
        print([worker.name for worker in enumerate()])

        # List active child workers
        print([child.name for child in active_children()])

**Output (Standard Python)**:

.. code-block:: text

    MainProcess
    601133
    2
    ['Daemon', 'MainProcess']
    ['Daemon']

**Output (Free-threaded Python)**:

.. code-block:: text

    MainThread
    135793751029632
    2
    ['MainThread', 'Daemon']
    ['Daemon']

In addition, :mod:`freethreading` offers :func:`~freethreading.get_backend()` function that returns the selected
parallelism backend. This can be useful for debugging. Here's how to use it:

.. code-block:: python

    from freethreading import get_backend

    print(get_backend())

**Output (Standard Python)**:

.. code-block:: text

    multiprocessing

**Output (Free-threaded Python)**:

.. code-block:: text

    threading

End-to-End Example: Parallel Primes
-----------------------------------

The following examples demonstrate finding primes in parallel using the low-level worker-queue pattern and the simpler
executor pattern.

Using ``Worker`` and ``Queue``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

This example uses workers and queues for fine-grained control over task distribution:

.. code-block:: python

    from freethreading import Queue, Worker

    def is_prime(n):
        if n < 2:
            return False
        for i in range(2, int(n ** 0.5) + 1):
            if n % i == 0:
                return False
        return True

    def worker(tasks, results):
        while True:
            number = tasks.get()
            if number is None:
                tasks.task_done()
                break
            if is_prime(number):
                results.put(number)
            tasks.task_done()

    if __name__ == "__main__":
        tasks = Queue()
        results = Queue()

        pool = [Worker(target=worker, args=(tasks, results)) for _ in range(4)]
        for w in pool:
            w.start()

        for candidate in range(500, 600):
            tasks.put(candidate)

        # Sentinel per worker to signal completion
        for _ in pool:
            tasks.put(None)

        tasks.join()
        for w in pool:
            w.join()

        primes = []
        while not results.empty():
            primes.append(results.get())

        primes.sort()
        print(f"Found {len(primes)} primes: {primes}")

**Output**:

.. code-block:: text

    Found 14 primes: [503, 509, 521, 523, 541, 547, 557, 563, 569, 571, 577, 587, 593, 599]

Using ``WorkerPoolExecutor``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The following example achieves the same result using :class:`~freethreading.WorkerPoolExecutor` for simplicity:

.. code-block:: python

    from freethreading import WorkerPoolExecutor

    def is_prime(n):
        if n < 2:
            return False
        for i in range(2, int(n ** 0.5) + 1):
            if n % i == 0:
                return False
        return True

    if __name__ == "__main__":
        with WorkerPoolExecutor() as executor:
            candidates = range(500, 600)
            primes = [
                n
                for n, prime in zip(candidates, executor.map(is_prime, candidates))
                if prime
            ]

        print(f"Found {len(primes)} primes: {primes}")

**Output**:

.. code-block:: text

    Found 14 primes: [503, 509, 521, 523, 541, 547, 557, 563, 569, 571, 577, 587, 593, 599]
