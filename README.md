<div align="center">

# freethreading — Thread-first true parallelism

[![PyPI Version](https://img.shields.io/pypi/v/free-threading.svg?label=PyPI)](https://pypi.org/project/free-threading/)
![Python Versions](https://img.shields.io/pypi/pyversions/free-threading?label=Python)
![License](https://img.shields.io/pypi/l/free-threading?label=License)
[![CI Build](https://github.com/iskandergaba/free-threading/actions/workflows/ci.yml/badge.svg)](https://github.com/iskandergaba/free-threading/actions/workflows/ci.yml)
[![Codecov](https://codecov.io/gh/iskandergaba/free-threading/graph/badge.svg?token=LWBRgtlX8j)](https://codecov.io/gh/iskandergaba/free-threading)
[![Docs](https://readthedocs.org/projects/freethreading/badge/?version=latest)](https://freethreading.readthedocs.io/en/latest)

`freethreading` is a lightweight wrapper that provides a unified API for true parallel execution in Python. It
automatically uses `threading` on free-threaded Python builds (where the
[Global Interpreter Lock (GIL)](https://docs.python.org/3/glossary.html#term-global-interpreter-lock) is disabled) and
falls back to `multiprocessing` on standard ones. This enables true parallelism across Python versions while preferring
the efficiency of [threads](https://en.wikipedia.org/wiki/Thread_(computing)) over
[processes](https://en.wikipedia.org/wiki/Process_(computing)) whenever possible.

</div>

## Installation

To install `freethreading`, simply run:

```shell
pip install free-threading
```

To install the latest development version, you can run:

```shell
pip install git+https://github.com/iskandergaba/free-threading.git
```

## Quick Start

`freethreading` is a drop-in replacement for *most* pre-existing `threading` and `multiprocessing` code. To achieve
this, the module exposes only non-deprecated common functionality shared between both backends while discarding any
backend-specific APIs. The following examples show how to get started.

`freethreading` remains consistent with the standard library, so wrapper classes work as drop-in replacements for those
used by `threading` and `multiprocessing`. Here's how they work:

```python
# threading
from queue import Queue
from threading import Event, Lock

# multiprocessing
from multiprocessing import Event, Lock, Queue

# freethreading (replaces both)
from freethreading import Event, Lock, Queue

if __name__ == "__main__":
    event = Event()
    lock = Lock()
    queue = Queue()
    print(lock.acquire())
    event.set()
    queue.put("data")
    print(event.is_set())
    print(queue.get())
    lock.release()
```

**Output**:

```
True
True
data
```

`freethreading` functions merge as much functionality from both backends as possible to ensure consistent behavior
across backends and simplify adoption. Here's what that looks like:

```python
# threading
from threading import enumerate, get_ident

# multiprocessing
from multiprocessing import active_children
from os import getpid

# freethreading (replaces both)
from freethreading import active_children, enumerate, get_ident

if __name__ == "__main__":
    print(len(active_children()))  # excludes current thread or process
    print(len(enumerate()))  # includes current thread or process
    print(get_ident())  # current thread or process identifier
```

**Output**:

```
0
1
140247834...
```

Only `Worker`, `WorkerPool`, `WorkerPoolExecutor`, and `current_worker` differ from the standard library naming, using
"worker" as a term for both threads and processes. Below is an example:

```python
# threading
from concurrent.futures import ThreadPoolExecutor
from threading import Thread, current_thread

# multiprocessing
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import Process, current_process

# freethreading (replaces both)
from freethreading import Worker, WorkerPool, WorkerPoolExecutor, current_worker

def greet():
    print(f"Hello from {current_worker().name}!")

def square(x):
    return x * x

if __name__ == "__main__":
    # MainThread or MainProcess
    print(current_worker().name)

    # Using Worker (Thread or Process) to run a task
    w = Worker(target=greet, name="MyWorker")
    w.start()
    w.join()

    # Using WorkerPool (Pool or ThreadPool) to distribute work
    with WorkerPool(workers=2) as pool:
        print(pool.map(square, range(5)))

    # Using WorkerPoolExecutor (ThreadPoolExecutor or ProcessPoolExecutor) to run a task
    with WorkerPoolExecutor(max_workers=2) as executor:
        future = executor.submit(greet)
```

**Output (Standard Python)**:

```
MainProcess
Hello from MyWorker!
[0, 1, 4, 9, 16]
Hello from ForkServerProcess-4!
```

**Output (Free-threaded Python)**:

```
MainThread
Hello from MyWorker!
[0, 1, 4, 9, 16]
Hello from ThreadPoolExecutor-0_0!
```

## Documentation

For more details, check out the full documentation at
[freethreading.readthedocs.io](https://freethreading.readthedocs.io).
