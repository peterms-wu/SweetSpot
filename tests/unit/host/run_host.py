"""`python -m sweetspot.host` for tests/unit/host/test_main.py, with this machine's API keys out of reach (a child
process does not get tests/conftest.py's fixture; the test also removes them from the environment).

    run_host.py [--noisy] <the local program's arguments...>

--noisy makes request handling print to standard output (print and a raw write to fd 1) first, the way a stray
print anywhere in the report would.
"""

import os
import runpy
import sys

from sweetspot import config

config._read_user_registry = lambda name: None

if "--noisy" in sys.argv:
    sys.argv.remove("--noisy")
    from sweetspot.host import service

    real = service.handle

    def noisy(*args, **kwargs):
        print("noise from print")
        sys.stdout.flush()
        os.write(1, b"noise on fd 1\n")
        return real(*args, **kwargs)

    service.handle = noisy

runpy.run_module("sweetspot.host", run_name="__main__", alter_sys=True)
