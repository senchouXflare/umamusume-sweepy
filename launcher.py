"""
Umamusume Sweepy Launcher
=========================
Single Launch: Pick one ADB device, run one instance on port 8071.
Multi Launch:  Detect all ADB devices, spawn one instance per device
               on ports 8071, 8072, 8073, …
After launch:  Management menu to stop individual or all instances.
"""

import os
import sys
import subprocess
import time
import webbrowser
import signal

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ADB_PATH = os.path.join(SCRIPT_DIR, "deps", "adb", "adb.exe")
BASE_PORT = 8071

# Track running instances: list of (device, port, process)
running_instances = []

# ── ADB helpers ──────────────────────────────────────────────────────

def run_adb(args, timeout=15):
    try:
        return subprocess.run(
            [ADB_PATH] + args,
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout,
        )
    except Exception:
        return None


def restart_adb():
    print("[*] Restarting ADB server...")
    run_adb(["kill-server"], timeout=10)
    time.sleep(1)
    run_adb(["start-server"], timeout=15)
    time.sleep(2)


def get_devices():
    result = run_adb(["devices"], timeout=10)
    if result is None or result.returncode != 0:
        return []
    devices = []
    for line in result.stdout.strip().split("\n")[1:]:
        line = line.strip()
        if line and "\t" in line:
            dev_id, status = line.split("\t", 1)
            if status.strip() == "device":
                devices.append(dev_id.strip())
    return devices

# ── Display helpers ──────────────────────────────────────────────────

def banner():
    print()
    print("=" * 52)
    print("       Umamusume Sweepy  —  Launcher")
    print("=" * 52)
    print()


def show_devices(devices):
    if not devices:
        print("  (no devices detected)")
        return
    for i, d in enumerate(devices, 1):
        print(f"  {i}. {d}")
    print()

# ── Spawn a sweepy instance ─────────────────────────────────────────

def spawn_instance(device, port, venv_python):
    """Start main.py in a new console window with UAT_DEVICE & UAT_PORT."""
    env = os.environ.copy()
    env["UAT_DEVICE"] = device
    env["UAT_PORT"] = str(port)

    # Use CREATE_NEW_CONSOLE to get a separate window we can track
    proc = subprocess.Popen(
        [venv_python, "main.py"],
        env=env,
        cwd=SCRIPT_DIR,
        creationflags=subprocess.CREATE_NEW_CONSOLE,
    )
    running_instances.append((device, port, proc))
    print(f"  [OK] {device}  →  http://127.0.0.1:{port}  (PID {proc.pid})")
    return proc


def find_python():
    """Return the venv python path, or fall back to sys.executable."""
    venv_py = os.path.join(SCRIPT_DIR, "venv", "Scripts", "python.exe")
    if os.path.isfile(venv_py):
        return venv_py
    return sys.executable

# ── Instance management ─────────────────────────────────────────────

def is_alive(proc):
    return proc.poll() is None


def stop_instance(idx):
    """Stop a single instance by index."""
    dev, port, proc = running_instances[idx]
    if is_alive(proc):
        print(f"  Stopping {dev} (port {port}, PID {proc.pid})...")
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        print(f"  [OK] Stopped.")
    else:
        print(f"  {dev} (port {port}) already stopped.")


def stop_all():
    """Stop all running instances."""
    alive = [(i, inst) for i, inst in enumerate(running_instances) if is_alive(inst[2])]
    if not alive:
        print("\n  No running instances to stop.")
        return
    print(f"\n  Stopping {len(alive)} instance(s)...")
    for i, (dev, port, proc) in alive:
        proc.terminate()
    for i, (dev, port, proc) in alive:
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        print(f"  [OK] {dev} (port {port}) stopped.")
    print("  All instances stopped.")


def show_status():
    """Show status of all instances."""
    print()
    for i, (dev, port, proc) in enumerate(running_instances):
        status = "RUNNING" if is_alive(proc) else "STOPPED"
        print(f"  {i+1}. [{status}]  {dev}  →  port {port}  (PID {proc.pid})")
    print()


def management_menu():
    """Post-launch management loop."""
    print("\n" + "=" * 52)
    print("       Instance Management")
    print("=" * 52)

    while True:
        alive_count = sum(1 for _, _, p in running_instances if is_alive(p))

        show_status()
        print(f"  Active: {alive_count}/{len(running_instances)}")
        print()
        print("  s) Status refresh")
        print("  1-N) Stop specific instance")
        print("  a) Stop ALL instances")
        print("  o) Open web UI in browser")
        print("  q) Quit launcher (instances keep running)")
        print("  x) Quit launcher + stop ALL")

        choice = input("\n  > ").strip().lower()

        if choice == "s":
            continue

        elif choice == "a":
            stop_all()

        elif choice == "q":
            print("\n  Launcher closed. Instances keep running in background.")
            break

        elif choice == "x":
            stop_all()
            print("\n  All stopped. Bye!")
            break

        elif choice == "o":
            alive = [(dev, port) for dev, port, p in running_instances if is_alive(p)]
            if not alive:
                print("  No running instances.")
            elif len(alive) == 1:
                webbrowser.open(f"http://127.0.0.1:{alive[0][1]}")
            else:
                print()
                for i, (dev, port) in enumerate(alive, 1):
                    print(f"    {i}. {dev} → port {port}")
                print(f"    a. Open ALL")
                sub = input("  Open which? ").strip().lower()
                if sub == "a":
                    for _, port in alive:
                        webbrowser.open(f"http://127.0.0.1:{port}")
                        time.sleep(0.3)
                else:
                    try:
                        idx = int(sub) - 1
                        if 0 <= idx < len(alive):
                            webbrowser.open(f"http://127.0.0.1:{alive[idx][1]}")
                    except ValueError:
                        pass

        else:
            # Try to parse as instance number
            try:
                num = int(choice)
                if 1 <= num <= len(running_instances):
                    stop_instance(num - 1)
                else:
                    print(f"  Invalid number. Use 1-{len(running_instances)}")
            except ValueError:
                print("  Unknown command.")

# ── Single Launch ────────────────────────────────────────────────────

def single_launch(devices):
    print("\n── Single Launch ──────────────────────────────")
    print()
    print("  a) Auto-detect (pick from list)")
    print("  m) Manual input device address")
    choice = input("\n  Select (a/m): ").strip().lower()

    selected = None

    if choice == "m":
        addr = input("  Enter device address (e.g. 127.0.0.1:5555): ").strip()
        if addr:
            if ":" in addr:
                run_adb(["connect", addr], timeout=10)
                time.sleep(1)
            selected = addr
    else:
        if not devices:
            print("\n  No devices found.")
            addr = input("  Enter device address manually (or Enter to quit): ").strip()
            if addr:
                if ":" in addr:
                    run_adb(["connect", addr], timeout=10)
                    time.sleep(1)
                selected = addr
        elif len(devices) == 1:
            selected = devices[0]
            print(f"\n  Auto-selected: {selected}")
        else:
            show_devices(devices)
            try:
                idx = int(input(f"  Pick device (1-{len(devices)}): ").strip())
                if 1 <= idx <= len(devices):
                    selected = devices[idx - 1]
            except (ValueError, KeyboardInterrupt):
                pass

    if not selected:
        print("\n  No device selected. Aborting.")
        return

    port = BASE_PORT
    python = find_python()
    print()
    spawn_instance(selected, port, python)
    time.sleep(2)
    webbrowser.open(f"http://127.0.0.1:{port}")

    # Enter management menu for single instance too
    management_menu()

# ── Multi Launch ─────────────────────────────────────────────────────

def multi_launch(devices):
    print("\n── Multi Launch ───────────────────────────────")
    print()

    if not devices:
        print("  No devices auto-detected.")
        print("  Enter device addresses separated by commas.")
        print("  Example: 127.0.0.1:5555, 127.0.0.1:5557")
        raw = input("\n  Devices: ").strip()
        if not raw:
            print("  No devices entered. Aborting.")
            return
        devices = [d.strip() for d in raw.split(",") if d.strip()]
        for d in devices:
            if ":" in d:
                run_adb(["connect", d], timeout=10)
        time.sleep(1)

    print(f"\n  Found {len(devices)} device(s):\n")

    assignments = []
    for i, dev in enumerate(devices):
        port = BASE_PORT + i
        assignments.append((dev, port))
        print(f"    {dev}  →  port {port}")

    print()
    confirm = input("  Launch all? (y/n): ").strip().lower()
    if confirm != "y":
        print("  Cancelled.")
        return

    python = find_python()
    print()
    for dev, port in assignments:
        spawn_instance(dev, port, python)
        time.sleep(1)

    print(f"\n  All {len(assignments)} instance(s) launched!")
    print()

    open_all = input("  Open all in browser? (y/n): ").strip().lower()
    if open_all == "y":
        for _, port in assignments:
            webbrowser.open(f"http://127.0.0.1:{port}")
            time.sleep(0.5)

    # Enter management menu
    management_menu()

# ── Main ─────────────────────────────────────────────────────────────

def main():
    os.chdir(SCRIPT_DIR)
    banner()

    restart_adb()
    devices = get_devices()

    print(f"  Detected {len(devices)} device(s):")
    show_devices(devices)

    print("  1) Single Launch  — one device, one instance")
    print("  2) Multi Launch   — all devices, separate instances")
    print("  q) Quit")
    choice = input("\n  Select mode (1/2/q): ").strip()

    if choice == "1":
        single_launch(devices)
    elif choice == "2":
        multi_launch(devices)
    else:
        print("\n  Bye!")


if __name__ == "__main__":
    main()
