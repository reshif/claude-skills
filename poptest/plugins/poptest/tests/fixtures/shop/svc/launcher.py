"""A launcher that starts the real service as a CHILD process, the way shell wrappers and
process managers do. Stopping the launcher alone would orphan the child, which then keeps the port.
Usage: python3 launcher.py PORT [ClassName] [warmup]"""
import os
import subprocess
import sys

child = subprocess.Popen([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "server.py"), *sys.argv[1:]])
sys.exit(child.wait())
