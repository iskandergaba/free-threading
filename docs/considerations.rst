Important Considerations
========================

Before using :mod:`freethreading`, it is important to understand when it is the right choice and what to watch out for.

When to Use ``freethreading``
-----------------------------

:mod:`freethreading` solves a specific problem: achieving true parallel execution across both standard and
free-threaded Python builds with one codebase. However, this portability comes at the cost of a reduced feature set and
constraints on how workers share data. With that in mind, :mod:`freethreading` works well for:

- Projects targeting both standard and free-threaded Python builds
- Projects whose needs fall within the common feature set of :mod:`threading` and :mod:`multiprocessing`
- Computationally intensive code that benefits from true parallelism on standard Python builds, with the
  added advantage of :mod:`threading`'s lower overhead on free-threaded builds

For anything else, :mod:`threading` or :mod:`multiprocessing` are likely better choices. If a project already relies on
backend-specific features like shared memory or thread-local storage, then the choice is either to use the
corresponding backend or to adapt the code to the common feature set of both.


Constraints and Pitfalls
------------------------

In addition to general concurrency pitfalls like proper resource cleanup and daemon behavior, :mod:`freethreading` has
a few of its own that stem from supporting consistent behavior across both :mod:`threading` and :mod:`multiprocessing`
backends.

Shared State
^^^^^^^^^^^^

Sharing state across workers through variables may produce unexpected results. Variables defined outside a worker's
function are handled differently depending on the backend — with :mod:`multiprocessing`, each process has its own
memory space, so changes made in one worker are not reflected in other workers. Here is an example:

.. code-block:: python
   :class: bad

   from freethreading import Worker

   counter = 0

   def increment():
       global counter
       counter += 1

   if __name__ == "__main__":
       workers = [Worker(target=increment) for _ in range(5)]
       for w in workers:
           w.start()
       for w in workers:
           w.join()

       print(counter) # Still 0 with multiprocessing!

**Output (Standard Python)**:

.. code-block:: text
   :class: bad

   0

**Output (Free-threaded Python)**:

.. code-block:: text
   :class: bad

   5

:class:`~freethreading.Queue` or :class:`~freethreading.SimpleQueue` should be used instead for passing data between
workers. Here is an example:

.. code-block:: python
   :class: good

   from freethreading import SimpleQueue, Worker

   def increment(results):
       results.put(1)

   if __name__ == "__main__":
       results = SimpleQueue()
       workers = [Worker(target=increment, args=(results,)) for _ in range(5)]
       for w in workers:
           w.start()
       for w in workers:
           w.join()

       total = sum(results.get() for _ in range(5))
       print(total)

**Output (Standard Python)**:

.. code-block:: text
   :class: good

   5

**Output (Free-threaded Python)**:

.. code-block:: text
   :class: good

   5

Picklability Requirement
^^^^^^^^^^^^^^^^^^^^^^^^

Since the :mod:`multiprocessing` backend requires serialization, data passed to workers must be `picklable
<https://docs.python.org/3/library/pickle.html>`_. The library validates this at :class:`~freethreading.Worker`
creation time, ensuring code works consistently regardless of which backend is active. Here's a quick example:

.. code-block:: python
   :class: bad

   from freethreading import Worker

   # This raises ValueError - lambdas aren't picklable
   worker = Worker(target=lambda: print("Hello!"))

**Output**:

.. code-block:: text
   :class: bad

   Traceback (most recent call last):
       ...
   ValueError: Worker arguments must be picklable for compatibility with multiprocessing backend...

Module-level functions are picklable and work with both backends. For instance:

.. code-block:: python
   :class: good

   from freethreading import Worker

   def greet():
       print("Hello!")

   if __name__ == "__main__":
       worker = Worker(target=greet)
       worker.start()
       worker.join()

**Output**:

.. code-block:: text
   :class: good

   Hello!

Non-Thread-Safe C Extensions
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

In free-threaded Python builds, the GIL is re-enabled at runtime when a C extension not marked as thread-safe is
loaded. Since :mod:`freethreading` determines its backend once at import time based on the current GIL state, loading
such an extension afterward means the library continues using the :mod:`threading` backend even though the GIL is now
enabled.

This is by design — switching backends mid-execution would cause incompatibilities between primitives created at
different times. To avoid this, import :mod:`freethreading` after loading any C extensions whose thread-safety is
unknown.

``Queue.qsize()`` on macOS
^^^^^^^^^^^^^^^^^^^^^^^^^^

On macOS, :meth:`freethreading.Queue.qsize` raises :exc:`NotImplementedError` with the :mod:`multiprocessing` backend
because ``sem_getvalue()`` is not implemented on that platform.


Development Tips
----------------

:mod:`freethreading` aims for consistent behavior across backends, but understanding the underlying runtime can help
when investigating issues and validating code. Below are a few tips that can help during development.

Checking the Backend
^^^^^^^^^^^^^^^^^^^^

Knowing which parallelism backend is being used can be helpful for debugging. Here's how to check it:

.. code-block:: python

   from freethreading import get_backend

   print(get_backend())

**Output (Standard Python)**:

.. code-block:: text

   multiprocessing

**Output (Free-threaded Python)**:

.. code-block:: text

   threading


Testing Across Backends
^^^^^^^^^^^^^^^^^^^^^^^

Testing code against both backends ensures it works regardless of which one :mod:`freethreading` selects. It is a great
way to catch some of the pitfalls mentioned above. Here is an example of how to do this using :mod:`pytest`:

.. code-block:: python
   :caption: pytest_example.py

   import pytest
   import sys

   @pytest.fixture(params=['threading', 'multiprocessing'])
   def backend(request, monkeypatch):
       if request.param == 'threading':
           monkeypatch.setattr(sys, '_is_gil_enabled', lambda: False)
       else:
           monkeypatch.setattr(sys, '_is_gil_enabled', lambda: True)

       # Clear module cache to re-import with new GIL status
       if 'freethreading' in sys.modules:
           del sys.modules['freethreading']

       import freethreading
       return freethreading

   def task():
       pass

   def test_worker(backend):
       worker = backend.Worker(target=task)
       worker.start()
       worker.join()
       assert not worker.is_alive()

**Output**:

.. code-block:: console

   $ pytest -v --no-header --tb=no pytest_example.py
   =========================== test session starts ===========================
   collected 2 items

   pytest_example.py::test_worker[threading] PASSED                    [ 50%]
   pytest_example.py::test_worker[multiprocessing] PASSED              [100%]

   ============================ 2 passed in 0.14s ============================

And here is an equivalent example using :mod:`unittest`:

.. code-block:: python
   :caption: unittest_example.py

   import sys
   import unittest

   def task():
       pass

   class BackendTestMixin:
       backend = None
       original_gil_enabled = None

       @classmethod
       def setUpClass(cls):
           cls.original_gil_enabled = getattr(sys, '_is_gil_enabled', None)

           if cls.backend == 'threading':
               sys._is_gil_enabled = lambda: False
           else:
               sys._is_gil_enabled = lambda: True

           if 'freethreading' in sys.modules:
               del sys.modules['freethreading']

           import freethreading
           cls.freethreading = freethreading

       @classmethod
       def tearDownClass(cls):
           if cls.original_gil_enabled is None:
               if hasattr(sys, '_is_gil_enabled'):
                   delattr(sys, '_is_gil_enabled')
           else:
               sys._is_gil_enabled = cls.original_gil_enabled

       def test_worker(self):
           worker = self.freethreading.Worker(target=task)
           worker.start()
           worker.join()
           self.assertFalse(worker.is_alive())

   class TestThreadingBackend(BackendTestMixin, unittest.TestCase):
       backend = 'threading'

   class TestMultiprocessingBackend(BackendTestMixin, unittest.TestCase):
       backend = 'multiprocessing'

**Output**:

.. code-block:: console

   $ python -m unittest -v unittest_example.py
   test_worker (unittest_example.TestMultiprocessingBackend.test_worker) ... ok
   test_worker (unittest_example.TestThreadingBackend.test_worker) ... ok

   ----------------------------------------------------------------------
   Ran 2 tests in 0.086s

   OK
