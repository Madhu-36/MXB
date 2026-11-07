"""
Every test run gets its own throwaway data folder. A source checkout keeps MXB's data next to
the code, so without this, running the tests would write fake entries into the real audit log,
memory, undo journal and logs.
"""
import os
import tempfile

if not os.environ.get("MXB_DATA_DIR"):
    os.environ["MXB_DATA_DIR"] = tempfile.mkdtemp(prefix="mxb-test-data-")
