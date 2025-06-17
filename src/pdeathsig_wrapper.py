import ctypes
import signal
import os
import sys

try:
    # Set PR_SET_PDEATHSIG so this process gets SIGKILL if its parent dies
    PR_SET_PDEATHSIG = 1
    libc = ctypes.CDLL("libc.so.6")
    ret = libc.prctl(PR_SET_PDEATHSIG, signal.SIGKILL)
    if ret != 0:
        print("prctl failed")
        sys.exit(1)

    # Replace this process with the target command (e.g., /bin/sleep 1000)
    os.execvp(sys.argv[1], sys.argv[1:])
except Exception as e:
    print(f"Wrapper failed: {e}")
    sys.exit(2)
