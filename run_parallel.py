import subprocess
import sys
import threading

def run_survey(i):
    proc = subprocess.Popen(
        [sys.executable, "fill_survey.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd="/Users/aashrithbandaru/insomnia_method",
    )
    for line in proc.stdout:
        print(f"[run {i}] {line}", end="", flush=True)
    proc.wait()
    print(f"[run {i}] Exited with code {proc.returncode}", flush=True)

if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    print(f"Launching {n} parallel survey runs...")
    threads = [threading.Thread(target=run_survey, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    print("All runs complete.")
