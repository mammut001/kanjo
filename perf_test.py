import time
import subprocess
import os
import tempfile
import shutil

dir = tempfile.mkdtemp(prefix="kanjo-perf-")
os.environ["KANJO_CONFIG_DIR"] = dir
os.environ["KANJO_TOKEI_DIR"] = dir

start = time.time()
subprocess.check_call(["python3", "-m", "kanjo", "config", "set", "antigravity_accounts.a@test.com.plan", "google_ai_pro"])
end = time.time()

print(f"Time: {end - start:.4f}s")
shutil.rmtree(dir)
