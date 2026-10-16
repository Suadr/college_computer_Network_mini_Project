
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import platform
import socket
import subprocess
import shutil
import os
import csv
import json
import re
import psutil
import threading


APP_TITLE = "Network Device Information System"


# ---------------- COMMAND HELPERS ----------------

def command_output(command, timeout=5):
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False
        )
        if result.returncode == 0:
            return result.stdout.strip()
        return ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def read_file(path):
    try:
        with open(path, encoding="utf-8") as file:
            return file.read().strip()
    except (OSError, UnicodeError):
        return "Not available"


def human_bytes(value):
    if value is None:
        return "Not available"

    value = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if value < 1024 or unit == "PB":
            return f"{value:.2f} {unit}"
        value /= 1024


def get_lscpu():
    output = command_output(["lscpu"])
    result = {}

    for line in output.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            result[key.strip()] = value.strip()

    return result


# ---------------- SYSTEM INFORMATION ----------------

def system_details():
    info = get_lscpu()

    hostname = socket.gethostname()

    try:
        ips = sorted({
            item[4][0]
            for item in socket.getaddrinfo(hostname, None)
            if item[0] in (socket.AF_INET, socket.AF_INET6)
        })
        ip_text = ", ".join(ips) or "Not available"
    except socket.gaierror:
        ip_text = "Not available"

    try:
        with open("/proc/uptime", encoding="utf-8") as file:
            seconds = int(float(file.read().split()[0]))
        days, seconds = divmod(seconds, 86400)
        hours, seconds = divmod(seconds, 3600)
        minutes = seconds // 60
        uptime = f"{days} days, {hours} hours, {minutes} minutes"
    except (OSError, ValueError, IndexError):
        uptime = "Not available"

    try:
        resolution = command_output(["xrandr"])
        match = re.search(r"current (\d+ x \d+)", resolution)
        screen = match.group(1) if match else "Not available"
    except Exception:
        screen = "Not available"

    return [
        ("Hostname", hostname),
        ("Operating System", platform.system()),
        ("Distribution", read_file("/etc/os-release").splitlines()[0]
         if read_file("/etc/os-release") != "Not available"
         else "Not available"),
        ("Kernel Version", platform.release()),
        ("Platform", platform.platform()),
        ("Machine Architecture", platform.machine()),
        ("Python Version", platform.python_version()),
        ("Processor", info.get("Model name", platform.processor())
         or "Not available"),
        ("CPU Architecture", info.get("Architecture", "Not available")),
        ("CPU Cores", psutil.cpu_count(logical=False) or "Not available"),
        ("CPU Threads", psutil.cpu_count(logical=True) or "Not available"),
        ("CPU Usage", f"{psutil.cpu_percent(interval=0.3):.1f}%"),
        ("Display Resolution", screen),
        ("Hostname IP Addresses", ip_text),
        ("System Uptime", uptime),
    ]


# ---------------- HARDWARE ----------------

def hardware_details():
    info = get_lscpu()

    model = read_file("/sys/class/dmi/id/product_name")
    if model == "Not available":
        model = read_file("/sys/firmware/devicetree/base/model")

    manufacturer = read_file("/sys/class/dmi/id/sys_vendor")
    product_version = read_file("/sys/class/dmi/id/product_version")
    bios_vendor = read_file("/sys/class/dmi/id/bios_vendor")
    bios_version = read_file("/sys/class/dmi/id/bios_version")

    gpu = command_output([
        "sh", "-c",
        "lspci 2>/dev/null | grep -Ei 'VGA|3D controller|Display controller'"
    ])

    if not gpu:
        gpu = "Not available"

    return [
        ("Manufacturer", manufacturer),
        ("Computer Model", model),
        ("Product Version", product_version),
        ("BIOS Vendor", bios_vendor),
        ("BIOS Version", bios_version),
        ("CPU Model", info.get("Model name", "Not available")),
        ("CPU Vendor", info.get("Vendor ID", "Not available")),
        ("CPU Sockets", info.get("Socket(s)", "Not available")),
        ("CPU Cores per Socket", info.get("Core(s) per socket", "Not available")),
        ("Virtualization", info.get("Virtualization", "Not available")),
        ("Graphics Adapter", gpu),
    ]


# ---------------- RAM ----------------

def memory_details():
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()

    return [
        ("Total RAM", human_bytes(mem.total)),
        ("Used RAM", human_bytes(mem.used)),
        ("Available RAM", human_bytes(mem.available)),
        ("RAM Usage", f"{mem.percent:.1f}%"),
        ("Free RAM (unused)", human_bytes(mem.free)),
        ("Total Swap", human_bytes(swap.total)),
        ("Used Swap", human_bytes(swap.used)),
        ("Swap Usage", f"{swap.percent:.1f}%"),
    ]


# ---------------- DISK AND PARTITIONS ----------------

def disk_details():
    rows = []

    output = command_output([
        "lsblk", "-J", "-b", "-o",
        "NAME,TYPE,SIZE,MODEL,ROTA,FSTYPE,MOUNTPOINTS"
    ])

    try:
        devices = json.loads(output).get("blockdevices", [])
    except (json.JSONDecodeError, AttributeError):
        devices = []

    def walk(device):
        name = device.get("name", "Unknown")
        dtype = device.get("type", "Unknown")
        size = human_bytes(device.get("size") or 0)
        model = device.get("model") or "Not reported"
        rota = device.get("rota")
        fstype = device.get("fstype") or "-"
        mounts = device.get("mountpoints") or []
        mount_text = ", ".join(m for m in mounts if m) or "-"

        if dtype == "disk":
            disk_type = (
                "HDD" if rota is True else
                "SSD" if rota is False else
                "Unknown"
            )
            rows.append((
                name, dtype, size, model,
                disk_type, fstype, mount_text
            ))
        elif dtype in ("part", "rom", "lvm", "crypt"):
            rows.append((
                name, dtype, size, model,
                "-", fstype, mount_text
            ))

        for child in device.get("children") or []:
            walk(child)

    for device in devices:
        walk(device)

    return rows


def filesystem_details():
    rows = []

    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
            rows.append((
                part.device,
                part.mountpoint,
                part.fstype or "-",
                human_bytes(usage.total),
                human_bytes(usage.used),
                human_bytes(usage.free),
                f"{usage.percent:.1f}%"
            ))
        except (PermissionError, OSError):
            continue

    return rows


# ---------------- NETWORK ----------------

def gateway():
    output = command_output(["ip", "route", "show", "default"])
    for line in output.splitlines():
        parts = line.split()
        if "via" in parts:
            return parts[parts.index("via") + 1]
    return "Not available"


def dns_servers():
    result = []
    try:
        with open("/etc/resolv.conf", encoding="utf-8") as file:
            for line in file:
                parts = line.split()
                if len(parts) >= 2 and parts[0] == "nameserver":
                    result.append(parts[1])
    except OSError:
        pass

    return ", ".join(dict.fromkeys(result)) or "Not available"


def interface_details():
    output = command_output(["ip", "-j", "address", "show"])

    try:
        interfaces = json.loads(output)
    except (json.JSONDecodeError, TypeError):
        interfaces = []

    rows = []

    for interface in interfaces:
        ips = []

        for address in interface.get("addr_info", []):
            family = address.get("family", "")
            local = address.get("local", "")
            prefix = address.get("prefixlen", "")

            if local:
                label = "IPv4" if family == "inet" else (
                    "IPv6" if family == "inet6" else family
                )
                ips.append(f"{label}: {local}/{prefix}")

        rows.append((
            interface.get("ifname", "Unknown"),
            interface.get("operstate", "Unknown"),
            interface.get("address", "Not available"),
            ", ".join(ips) or "No IP address"
        ))

    return rows


def network_config():
    return [
        ("Default Gateway", gateway()),
        ("DNS Servers", dns_servers()),
        ("Routing Table", command_output(["ip", "route", "show"])
         or "Not available"),
        ("Interface Count", str(len(interface_details()))),
    ]


# ---------------- GUI TABLE HELPERS ----------------

def make_table(parent, columns, headings, widths):
    frame = ttk.Frame(parent)
    frame.pack(fill="both", expand=True)

    table = ttk.Treeview(
        frame, columns=columns, show="headings", height=12
    )

    for col, heading, width in zip(columns, headings, widths):
        table.heading(col, text=heading)
        table.column(col, width=width, anchor="w")

    yscroll = ttk.Scrollbar(
        frame, orient="vertical", command=table.yview
    )
    xscroll = ttk.Scrollbar(
        frame, orient="horizontal", command=table.xview
    )

    table.configure(
        yscrollcommand=yscroll.set,
        xscrollcommand=xscroll.set
    )

    table.grid(row=0, column=0, sticky="nsew")
    yscroll.grid(row=0, column=1, sticky="ns")
    xscroll.grid(row=1, column=0, sticky="ew")

    frame.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)

    return table


def fill_table(table, rows):
    table.delete(*table.get_children())
    for row in rows:
        table.insert("", "end", values=row)


def copy_selected(table):
    selected = table.selection()

    if not selected:
        messagebox.showwarning(
            "Select Information", "Select a row first."
        )
        return

    values = table.item(selected[0], "values")
    root.clipboard_clear()
    root.clipboard_append(" | ".join(map(str, values)))
    status.set("Selected information copied.")


# ---------------- SEARCH ----------------

def filter_interfaces(*args):
    query = search_var.get().strip().lower()
    rows = interface_details()

    if query:
        rows = [
            row for row in rows
            if any(query in str(value).lower() for value in row)
        ]

    fill_table(network_table, rows)


# ---------------- EXPORT ----------------

def export_report():
    path = filedialog.asksaveasfilename(
        title="Save Full System Report",
        defaultextension=".txt",
        filetypes=[
            ("Text Report", "*.txt"),
            ("CSV Report", "*.csv")
        ]
    )

    if not path:
        return

    sections = [
        ("SYSTEM INFORMATION", system_details()),
        ("HARDWARE INFORMATION", hardware_details()),
        ("RAM AND SWAP", memory_details()),
        ("NETWORK CONFIGURATION", network_config()),
    ]

    disks = [
        (" | ".join(map(str, row)))
        for row in disk_details()
    ]
    filesystems = [
        (" | ".join(map(str, row)))
        for row in filesystem_details()
    ]
    interfaces = [
        (" | ".join(map(str, row)))
        for row in interface_details()
    ]

    try:
        if path.lower().endswith(".csv"):
            with open(path, "w", newline="", encoding="utf-8") as file:
                writer = csv.writer(file)
                writer.writerow(["Section", "Name", "Value"])

                for section, rows in sections:
                    for name, value in rows:
                        writer.writerow([section, name, value])

                for row in disk_details():
                    writer.writerow(["Physical Disks", *row])

                for row in filesystem_details():
                    writer.writerow(["Filesystems", *row])

                for row in interface_details():
                    writer.writerow(["Network Interfaces", *row])
        else:
            with open(path, "w", encoding="utf-8") as file:
                file.write(APP_TITLE + "\n")
                file.write("=" * 55 + "\n\n")

                for section, rows in sections:
                    file.write(section + "\n")
                    file.write("-" * 40 + "\n")
                    for name, value in rows:
                        file.write(f"{name}: {value}\n")
                    file.write("\n")

                file.write("PHYSICAL DISKS AND PARTITIONS\n")
                for row in disks:
                    file.write(row + "\n")

                file.write("\nFILESYSTEM USAGE\n")
                for row in filesystems:
                    file.write(row + "\n")

                file.write("\nNETWORK INTERFACES\n")
                for row in interfaces:
                    file.write(row + "\n")

        messagebox.showinfo(
            "Export Complete", "Full report saved successfully."
        )
        status.set("Report exported successfully.")

    except OSError as error:
        messagebox.showerror("Export Error", str(error))


# ---------------- DIAGNOSTICS ----------------

def ping_test():
    host = ping_entry.get().strip()

    if (
        not host
        or host.startswith("-")
        or any(char.isspace() for char in host)
    ):
        messagebox.showwarning(
            "Invalid Input", "Enter a hostname or IP address."
        )
        return

    if not shutil.which("ping"):
        messagebox.showerror(
            "Missing Tool", "Install iputils-ping first."
        )
        return

    ping_button.config(state="disabled")
    ping_result.set("Testing connection...")
    status.set("Ping test running...")

    def worker():
        output = command_output(
            ["ping", "-c", "1", "-W", "2", "--", host],
            timeout=4
        )

        if "bytes from" in output or "bytes=" in output:
            result = f"Reply received from {host}\n\n{output}"
        else:
            result = (
                f"No reply from {host} or request timed out.\n"
                "The destination may block ping requests.\n\n" + output
            )

        root.after(0, lambda: finish_ping(result))

    threading.Thread(target=worker, daemon=True).start()


def finish_ping(result):
    ping_result.set(result)
    ping_button.config(state="normal")
    status.set("Ping test completed.")


def dns_lookup():
    host = dns_entry.get().strip()

    if (
        not host
        or host.startswith("-")
        or any(char.isspace() for char in host)
    ):
        messagebox.showwarning(
            "Invalid Input", "Enter a hostname or domain name."
        )
        return

    dns_result.set("Looking up...")

    def worker():
        try:
            results = socket.getaddrinfo(host, None)
            addresses = sorted({item[4][0] for item in results})
            result = "\n".join(addresses) or "No address found."
        except socket.gaierror as error:
            result = f"Lookup failed: {error}"

        root.after(0, lambda: dns_result.set(result))

    threading.Thread(target=worker, daemon=True).start()


# ---------------- APPLICATION WINDOW ----------------

root = tk.Tk()
root.title(APP_TITLE)
root.geometry("1050x700")
root.minsize(760, 500)

style = ttk.Style()
if "clam" in style.theme_names():
    style.theme_use("clam")

ttk.Label(
    root,
    text=APP_TITLE,
    font=("Arial", 18, "bold")
).pack(pady=(12, 3))

ttk.Label(
    root,
    text="Complete computer hardware, memory, storage and network report"
).pack(pady=(0, 10))

notebook = ttk.Notebook(root)
notebook.pack(fill="both", expand=True, padx=12, pady=5)

tabs = {}
for name, title in [
    ("system", "System"),
    ("hardware", "Hardware"),
    ("ram", "RAM"),
    ("disks", "HDD / SSD"),
    ("filesystems", "Partitions"),
    ("network", "Network"),
    ("config", "Network Settings"),
    ("diagnostics", "Diagnostics"),
]:
    tabs[name] = ttk.Frame(notebook, padding=10)
    notebook.add(tabs[name], text=title)


system_table = make_table(
    tabs["system"], ("name", "value"),
    ("Information", "Details"), (250, 700)
)

hardware_table = make_table(
    tabs["hardware"], ("name", "value"),
    ("Hardware Item", "Details"), (250, 700)
)

ram_table = make_table(
    tabs["ram"], ("name", "value"),
    ("Memory Information", "Details"), (250, 700)
)

disk_table = make_table(
    tabs["disks"],
    ("name", "type", "size", "model", "media", "fs", "mount"),
    ("Device", "Type", "Size", "Model", "Media", "Filesystem", "Mount"),
    (100, 75, 100, 180, 80, 100, 220)
)

filesystem_table = make_table(
    tabs["filesystems"],
    ("device", "mount", "fs", "total", "used", "free", "percent"),
    ("Device", "Mount Point", "Filesystem", "Total", "Used", "Free", "Used %"),
    (130, 180, 100, 100, 100, 100, 80)
)

search_row = ttk.Frame(tabs["network"])
search_row.pack(fill="x", pady=(0, 8))

ttk.Label(search_row, text="Search:").pack(side="left")

search_var = tk.StringVar()
ttk.Entry(
    search_row, textvariable=search_var
).pack(side="left", fill="x", expand=True, padx=8)

search_var.trace_add("write", filter_interfaces)

network_table = make_table(
    tabs["network"],
    ("name", "state", "mac", "ips"),
    ("Interface", "Status", "MAC Address", "IP Addresses"),
    (150, 100, 180, 500)
)

config_table = make_table(
    tabs["config"], ("name", "value"),
    ("Network Setting", "Details"), (250, 700)
)

ttk.Label(
    tabs["diagnostics"], text="Ping Test",
    font=("Arial", 12, "bold")
).pack(anchor="w", pady=(0, 5))

ping_row = ttk.Frame(tabs["diagnostics"])
ping_row.pack(fill="x")

ping_entry = ttk.Entry(ping_row)
ping_entry.insert(0, "1.1.1.1")
ping_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

ping_button = ttk.Button(
    ping_row, text="Run Ping", command=ping_test
)
ping_button.pack(side="left")

ping_result = tk.StringVar(value="Enter a hostname or IP address.")
ttk.Label(
    tabs["diagnostics"],
    textvariable=ping_result,
    wraplength=900,
    justify="left"
).pack(anchor="w", pady=10)

ttk.Separator(tabs["diagnostics"]).pack(fill="x", pady=10)

ttk.Label(
    tabs["diagnostics"], text="DNS / Hostname Lookup",
    font=("Arial", 12, "bold")
).pack(anchor="w", pady=(0, 5))

dns_row = ttk.Frame(tabs["diagnostics"])
dns_row.pack(fill="x")

dns_entry = ttk.Entry(dns_row)
dns_entry.insert(0, "example.com")
dns_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

ttk.Button(
    dns_row, text="Lookup", command=dns_lookup
).pack(side="left")

dns_result = tk.StringVar(value="Enter a domain and click Lookup.")
ttk.Label(
    tabs["diagnostics"],
    textvariable=dns_result,
    wraplength=900,
    justify="left"
).pack(anchor="w", pady=10)


def refresh_all():
    fill_table(system_table, system_details())
    fill_table(hardware_table, hardware_details())
    fill_table(ram_table, memory_details())
    fill_table(disk_table, disk_details())
    fill_table(filesystem_table, filesystem_details())
    filter_interfaces()
    fill_table(config_table, network_config())
    status.set("All available information refreshed.")


bottom = ttk.Frame(root, padding=10)
bottom.pack(fill="x")

status = tk.StringVar(value="Ready.")

ttk.Label(bottom, textvariable=status).pack(side="left")

ttk.Button(
    bottom, text="Refresh All", command=refresh_all
).pack(side="right", padx=4)

ttk.Button(
    bottom, text="Export Full Report", command=export_report
).pack(side="right", padx=4)

ttk.Button(
    bottom,
    text="Copy Selected",
    command=lambda: copy_selected(
        [
            system_table, hardware_table, ram_table, disk_table,
            filesystem_table, network_table, config_table
        ][max(0, min(notebook.index("current"), 6))]
    )
).pack(side="right", padx=4)

refresh_all()
root.mainloop()
