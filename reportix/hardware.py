"""
All the "go poke the OS/hardware and figure out what's installed" logic lives
here, kept separate from the Qt UI and the PDF rendering so each piece can be
tested / reused independently.

Every public getter is defensive: if a value can't be determined (missing
tool, insufficient permissions, unsupported platform, ...) it degrades to a
clearly-labelled "Unknown ..." string / empty list instead of raising, so a
single failed probe never takes down the whole scan.
"""

import json
import os
import platform
import subprocess
from datetime import datetime

import psutil
import cpuinfo

try:
    import GPUtil
except ImportError:
    GPUtil = None


# --------------------------------------------------------------------------
# Small shared helpers
# --------------------------------------------------------------------------

def get_size(bytes_, suffix="B"):
    """Human readable byte size, e.g. 1253656 -> '1.20MB'."""
    factor = 1024
    for unit in ["", "K", "M", "G", "T", "P"]:
        if bytes_ < factor:
            return f"{bytes_:.2f} {unit}{suffix}"
        bytes_ /= factor
    return f"{bytes_:.2f} E{suffix}"


def _run_powershell_json(ps_body, timeout=15):
    """
    Run a PowerShell pipeline and get the result back as parsed JSON.

    Using `ConvertTo-Json` instead of hand-parsing `Format-List` text output
    is far more robust (no guessing at line wrapping / localized field
    ordering) and gives us real types back. WMI cmdlets return a single
    object (dict) when there's exactly one result and a JSON array when
    there are several, so callers need to handle both.
    Returns None on any failure (missing powershell, WMI class unavailable,
    timeout, malformed output, etc).
    """
    try:
        full_cmd = (
            f'powershell -NoProfile -Command "{ps_body} | ConvertTo-Json -Depth 4"'
        )
        output = subprocess.check_output(
            full_cmd, shell=True, text=True, errors="ignore",
            stderr=subprocess.DEVNULL, timeout=timeout,
        ).strip()
        if not output:
            return None
        return json.loads(output)
    except Exception:
        return None


def _as_list(data):
    if data is None:
        return []
    return data if isinstance(data, list) else [data]


# --------------------------------------------------------------------------
# Motherboard
# --------------------------------------------------------------------------

def get_motherboard_info():
    board = "Unknown Motherboard"
    system = platform.system()
    try:
        if system == "Windows":
            data = _run_powershell_json(
                "Get-WmiObject Win32_BaseBoard | Select-Object Manufacturer, Product"
            )
            if data:
                mfg = (data.get("Manufacturer") or "").strip()
                prod = (data.get("Product") or "").strip()
                if mfg or prod:
                    board = f"{mfg} {prod}".strip()

        elif system == "Linux":
            mfg, prod = "", ""
            if os.path.exists("/sys/class/dmi/id/board_vendor"):
                with open("/sys/class/dmi/id/board_vendor", "r") as f:
                    mfg = f.read().strip()
            if os.path.exists("/sys/class/dmi/id/board_name"):
                with open("/sys/class/dmi/id/board_name", "r") as f:
                    prod = f.read().strip()
            if mfg or prod:
                board = f"{mfg} {prod}".strip()

        elif system == "Darwin":
            output = subprocess.check_output(
                ["system_profiler", "SPHardwareDataType"],
                text=True, errors="ignore", timeout=10,
            )
            model = ""
            for line in output.split("\n"):
                if "Model Identifier" in line or "Model Name" in line:
                    val = line.split(":", 1)[-1].strip()
                    if val and val not in model:
                        model = f"{model} {val}".strip()
            if model:
                board = f"Apple {model}"
    except Exception:
        pass
    return board if board else "Standard Motherboard"


# --------------------------------------------------------------------------
# BIOS / Firmware
# --------------------------------------------------------------------------

def get_bios_info():
    """
    Returns a plain "Unknown BIOS" string whenever nothing could be
    detected - never a made-up placeholder - matching the original
    behaviour the app relied on.
    """
    bios = "Unknown BIOS"
    system = platform.system()
    try:
        if system == "Windows":
            data = _run_powershell_json(
                "Get-WmiObject Win32_BIOS | "
                "Select-Object Manufacturer, SMBIOSBIOSVersion, ReleaseDate"
            )
            if data:
                mfg = (data.get("Manufacturer") or "").strip()
                ver = (data.get("SMBIOSBIOSVersion") or "").strip()
                if mfg or ver:
                    bios = f"{mfg} {ver}".strip()

        elif system == "Linux":
            vendor, version, date = "", "", ""
            paths = {
                "vendor": "/sys/class/dmi/id/bios_vendor",
                "version": "/sys/class/dmi/id/bios_version",
                "date": "/sys/class/dmi/id/bios_date",
            }
            for key, path in paths.items():
                if os.path.exists(path):
                    try:
                        with open(path, "r") as f:
                            val = f.read().strip()
                        if key == "vendor":
                            vendor = val
                        elif key == "version":
                            version = val
                        else:
                            date = val
                    except PermissionError:
                        continue
            parts = [p for p in (vendor, version) if p]
            if parts:
                bios = " ".join(parts)
                if date:
                    bios += f" ({date})"

        elif system == "Darwin":
            # Macs use EFI firmware rather than a classic BIOS - report the
            # Boot ROM / System Firmware version, which is the closest
            # equivalent.
            output = subprocess.check_output(
                ["system_profiler", "SPHardwareDataType"],
                text=True, errors="ignore", timeout=10,
            )
            for line in output.split("\n"):
                if "Boot ROM" in line or "System Firmware" in line:
                    val = line.split(":", 1)[-1].strip()
                    if val:
                        bios = val
                    break
    except Exception:
        pass
    return bios if bios else "Unknown BIOS"


# --------------------------------------------------------------------------
# GPU
# --------------------------------------------------------------------------

def _read_linux_sysfs_vram():
    """Map DRM card index -> human-readable VRAM size, when the kernel
    driver exposes it (works for amdgpu/nouveau; NVIDIA's proprietary
    driver usually does not expose this file)."""
    vram_by_index = {}
    drm_path = "/sys/class/drm"
    try:
        if os.path.isdir(drm_path):
            for entry in sorted(os.listdir(drm_path)):
                if not entry.startswith("card") or "-" in entry:
                    continue
                vram_file = os.path.join(drm_path, entry, "device", "mem_info_vram_total")
                if os.path.exists(vram_file):
                    with open(vram_file, "r") as f:
                        vram_bytes = int(f.read().strip())
                    idx = int(entry.replace("card", ""))
                    vram_by_index[idx] = get_size(vram_bytes)
    except Exception:
        pass
    return vram_by_index


def get_gpu_info():
    gpus = []
    system = platform.system()

    # 1) GPUtil (NVIDIA, via nvidia-smi under the hood)
    if GPUtil:
        try:
            for gpu in GPUtil.getGPUs():
                vram = get_size(gpu.memoryTotal * 1024 * 1024, "B")
                gpus.append(f"{gpu.name} ({vram} VRAM)")
        except Exception:
            pass

    # 2) Call nvidia-smi directly. Covers systems where the driver/tool is
    #    present but the optional GPUtil package isn't installed, or GPUtil
    #    failed to parse its output.
    if not gpus:
        try:
            output = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=name,memory.total",
                 "--format=csv,noheader,nounits"],
                text=True, errors="ignore", stderr=subprocess.DEVNULL, timeout=10,
            )
            for line in output.strip().split('\n'):
                if not line.strip():
                    continue
                parts = [p.strip() for p in line.split(',')]
                if len(parts) == 2:
                    name, mem_mib = parts
                    try:
                        vram = get_size(float(mem_mib) * 1024 * 1024, "B")
                        gpus.append(f"{name} ({vram} VRAM)")
                    except ValueError:
                        gpus.append(name)
        except Exception:
            pass

    # 3) Windows fallback via WMI, including AdapterRAM for VRAM
    if not gpus and system == "Windows":
        try:
            data = _run_powershell_json(
                "Get-WmiObject Win32_VideoController | Select-Object Name, AdapterRAM"
            )
            for item in _as_list(data):
                name = (item.get("Name") or "").strip()
                if not name:
                    continue
                vram_suffix = ""
                try:
                    ram_bytes = int(item.get("AdapterRAM") or 0)
                    if ram_bytes > 0:
                        vram_suffix = f" ({get_size(ram_bytes)} VRAM)"
                except (TypeError, ValueError):
                    pass
                gpus.append(f"{name}{vram_suffix}")
        except Exception:
            pass

    # 4) Linux fallback: lspci for the GPU name(s), sysfs for VRAM (AMD/nouveau)
    if not gpus and system == "Linux":
        lspci_names = []
        try:
            output = subprocess.check_output("lspci | grep -i vga", shell=True, text=True, errors="ignore")
            lspci_names = [line.split(':', 2)[-1].strip() for line in output.split('\n') if line.strip()]
        except Exception:
            pass

        vram_by_index = _read_linux_sysfs_vram()

        if lspci_names:
            for i, name in enumerate(lspci_names):
                vram = vram_by_index.get(i)
                gpus.append(f"{name} ({vram} VRAM)" if vram else name)
        elif vram_by_index:
            for idx, vram in vram_by_index.items():
                gpus.append(f"GPU {idx} ({vram} VRAM)")

    return ", ".join(gpus) if gpus else "Standard Display Adapter"


# --------------------------------------------------------------------------
# RAM - summary + per-stick detail (brand, part number, speed, capacity)
# --------------------------------------------------------------------------

def get_ram_summary():
    svmem = psutil.virtual_memory()
    try:
        swap = psutil.swap_memory()
        swap_total = get_size(swap.total)
        swap_usage = f"{swap.percent}%" if swap.total else "N/A"
    except Exception:
        swap_total, swap_usage = "Unknown", "N/A"

    return {
        "Total RAM": get_size(svmem.total),
        "Available RAM": get_size(svmem.available),
        "RAM Usage": f"{svmem.percent}%",
        "Total Swap": swap_total,
        "Swap Usage": swap_usage,
    }


def _clean(value, default="Unknown"):
    value = (value or "").strip()
    return value if value else default


def _parse_dmidecode_memory(output):
    """Parse `dmidecode --type 17` text output into a list of stick dicts."""
    modules = []
    for block in output.split("\n\n"):
        if "Memory Device" not in block:
            continue
        info = {}
        for line in block.split("\n"):
            line = line.strip()
            if ":" not in line:
                continue
            key, val = line.split(":", 1)
            info[key.strip()] = val.strip()

        size = info.get("Size", "")
        if not size or "No Module" in size:
            continue  # empty slot

        modules.append({
            "Slot": _clean(info.get("Locator"), "N/A"),
            "Manufacturer": _clean(info.get("Manufacturer")),
            "Part Number": _clean(info.get("Part Number")),
            "Serial Number": _clean(info.get("Serial Number"), ""),
            "Capacity": size,
            "Speed": _clean(info.get("Speed")),
        })
    return modules


def _parse_macos_memory(output):
    """Parse `system_profiler SPMemoryDataType` text output."""
    modules = []
    current = None
    for raw_line in output.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        # Bank / slot headers look like "BANK 0/DIMM0:" with no further ':'
        # content on the same line.
        if line.endswith(":") and line.count(":") == 1:
            if current and current.get("Capacity"):
                modules.append(current)
            current = {"Slot": line[:-1]}
            continue
        if current is None:
            continue
        if ":" in line:
            key, val = line.split(":", 1)
            key, val = key.strip(), val.strip()
            if key == "Size" and val and val != "empty":
                current["Capacity"] = val
            elif key == "Speed":
                current["Speed"] = val
            elif key == "Manufacturer":
                current["Manufacturer"] = val
            elif key == "Part Number":
                current["Part Number"] = val
            elif key == "Serial Number":
                current["Serial Number"] = val
    if current and current.get("Capacity"):
        modules.append(current)

    for m in modules:
        m.setdefault("Manufacturer", "Unknown")
        m.setdefault("Part Number", "Unknown")
        m.setdefault("Capacity", "Unknown")
        m.setdefault("Speed", "Unknown")
        m.setdefault("Serial Number", "")
    return modules


# --------------------------------------------------------------------------
# RAM - de-duplication
# --------------------------------------------------------------------------

def _dedupe_ram_modules(modules):
    """
    Some systems report the same physical memory stick more than once - a
    known quirk of Windows' Win32_PhysicalMemory (and occasionally
    dmidecode on certain BIOS/firmware) where a single DIMM shows up as
    two or more practically identical rows. That made Reportix report,
    say, "2 sticks" on a machine that's physically got just 1.

    Collapse rows that clearly refer to the same physical module down to
    one. The Serial Number is the most reliable "this is physically the
    same stick" signal, so it's preferred as the de-duplication key
    whenever it's actually populated with a real value; otherwise we fall
    back to the combination of fields the user can actually see (slot,
    manufacturer, part number, capacity, speed) - if all of those match,
    it's the same row being reported twice, not two different sticks.
    """
    placeholder_serials = {"", "unknown", "none", "n/a", "0", "0000000000", "serial number"}
    seen = set()
    deduped = []
    for m in modules:
        serial = _clean(m.get("Serial Number"), "").strip()
        if serial and serial.lower() not in placeholder_serials:
            key = ("serial", serial.lower())
        else:
            key = (
                "fields",
                m.get("Slot"), m.get("Manufacturer"),
                m.get("Part Number"), m.get("Capacity"), m.get("Speed"),
            )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(m)
    return deduped


def get_ram_modules():
    """
    Best-effort list of installed RAM sticks: [{Slot, Manufacturer,
    Part Number, Capacity, Speed}, ...]. Returns [] when the platform
    doesn't expose this (e.g. dmidecode needs root on most Linux distros)
    rather than guessing - the UI/PDF show a clear note in that case.
    """
    modules = []
    system = platform.system()
    try:
        if system == "Windows":
            data = _run_powershell_json(
                "Get-WmiObject Win32_PhysicalMemory | Select-Object "
                "BankLabel, DeviceLocator, Manufacturer, PartNumber, SerialNumber, "
                "Capacity, Speed, ConfiguredClockSpeed"
            )
            for item in _as_list(data):
                try:
                    capacity_bytes = int(item.get("Capacity") or 0)
                except (TypeError, ValueError):
                    capacity_bytes = 0
                speed = item.get("ConfiguredClockSpeed") or item.get("Speed") or ""
                slot = item.get("BankLabel") or item.get("DeviceLocator") or "N/A"
                modules.append({
                    "Slot": _clean(slot, "N/A"),
                    "Manufacturer": _clean(item.get("Manufacturer")),
                    "Part Number": _clean(item.get("PartNumber")),
                    "Serial Number": _clean(item.get("SerialNumber"), ""),
                    "Capacity": get_size(capacity_bytes) if capacity_bytes else "Unknown",
                    "Speed": f"{speed} MHz" if speed else "Unknown",
                })

        elif system == "Linux":
            output = subprocess.check_output(
                ["dmidecode", "--type", "17"],
                text=True, errors="ignore", stderr=subprocess.DEVNULL, timeout=10,
            )
            modules = _parse_dmidecode_memory(output)

        elif system == "Darwin":
            output = subprocess.check_output(
                ["system_profiler", "SPMemoryDataType"],
                text=True, errors="ignore", timeout=10,
            )
            modules = _parse_macos_memory(output)
    except Exception:
        modules = []

    # Collapse any duplicate rows the OS/firmware reported for the same
    # physical stick, then drop the internal-only Serial Number field
    # before handing the list back to the UI / PDF report.
    modules = _dedupe_ram_modules(modules)
    for m in modules:
        m.pop("Serial Number", None)
    return modules


# --------------------------------------------------------------------------
# OS name / update (feature) version / distro / build
# --------------------------------------------------------------------------

_MACOS_CODENAMES = {
    15: "Sequoia", 14: "Sonoma", 13: "Ventura", 12: "Monterey",
    11: "Big Sur", 10: "Catalina / earlier",
}


def _macos_codename(mac_ver):
    try:
        major = int(mac_ver.split(".")[0])
        return _MACOS_CODENAMES.get(major, "")
    except Exception:
        return ""


def get_os_version_details():
    """
    Returns {"OS Name", "OS Update / Version", "OS Build"}.

    - Windows: product name + the feature-update codename Windows itself
      shows in Settings (e.g. "23H2") + full build.UBR (e.g. "22631.3007").
    - Linux: distro pretty name (from /etc/os-release) + its version +
      kernel release, so both "which distro" and "which update" are covered.
    - macOS: marketing name/codename + version + Darwin build.
    - Anything else: best-effort fallback using `platform`.
    """
    system = platform.system()

    if system == "Windows":
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Windows NT\CurrentVersion",
            )

            def _reg(name, default=""):
                try:
                    return str(winreg.QueryValueEx(key, name)[0])
                except FileNotFoundError:
                    return default

            product_name = _reg("ProductName", f"Windows {platform.release()}")
            display_version = _reg("DisplayVersion") or _reg("ReleaseId")
            build = _reg("CurrentBuildNumber", platform.version().split(".")[-1])
            ubr = _reg("UBR")
            build_full = f"{build}.{ubr}" if ubr else build

            # Known Microsoft quirk: Windows 11 still reports itself as
            # "Windows 10 <Edition>" under the ProductName registry value -
            # that string was never updated when Windows 11 shipped. Build
            # 22000 is where Windows 11 starts, so once we're above that
            # threshold we correct the name ourselves rather than trusting
            # ProductName verbatim; the edition part of the string (Home,
            # Pro, Enterprise, ...) is still accurate and is preserved as-is.
            try:
                build_num = int(build)
            except (TypeError, ValueError):
                build_num = 0

            if build_num >= 22000 and "Windows 10" in product_name:
                product_name = product_name.replace("Windows 10", "Windows 11")
            elif build_num >= 22000 and "Windows 11" not in product_name:
                product_name = f"Windows 11 {product_name}".strip()

            os_name = product_name
            if display_version:
                os_name += f" {display_version}"

            return {
                "OS Name": os_name,
                "OS Update / Version": display_version or "Unknown",
                "OS Build": build_full,
            }
        except Exception:
            return {
                "OS Name": f"Windows {platform.release()}",
                "OS Update / Version": "Unknown",
                "OS Build": platform.version(),
            }

    elif system == "Linux":
        pretty_name, distro_name, distro_version = "", "Unknown Distribution", "Unknown"
        try:
            if os.path.exists("/etc/os-release"):
                info = {}
                with open("/etc/os-release", "r") as f:
                    for line in f:
                        line = line.strip()
                        if not line or "=" not in line or line.startswith("#"):
                            continue
                        key, val = line.split("=", 1)
                        info[key] = val.strip().strip('"')
                pretty_name = info.get("PRETTY_NAME", "")
                distro_name = info.get("NAME", distro_name)
                distro_version = info.get("VERSION") or info.get("VERSION_ID") or distro_version
        except Exception:
            pass

        kernel = platform.release()
        return {
            "OS Name": pretty_name or distro_name,
            "OS Update / Version": distro_version,
            "OS Build": f"Linux kernel {kernel}",
        }

    elif system == "Darwin":
        try:
            mac_ver = platform.mac_ver()[0] or "Unknown"
            codename = _macos_codename(mac_ver)
            os_name = f"macOS {codename}".strip() if codename else "macOS"
            return {
                "OS Name": os_name,
                "OS Update / Version": mac_ver,
                "OS Build": platform.version(),
            }
        except Exception:
            return {
                "OS Name": "macOS",
                "OS Update / Version": "Unknown",
                "OS Build": platform.version(),
            }

    return {
        "OS Name": f"{platform.system()} {platform.release()}".strip(),
        "OS Update / Version": "Unknown",
        "OS Build": platform.version(),
    }


# --------------------------------------------------------------------------
# Uptime
# --------------------------------------------------------------------------

def get_uptime_str():
    try:
        boot_time = psutil.boot_time()
        uptime_seconds = datetime.now().timestamp() - boot_time
        hours, remainder = divmod(int(uptime_seconds), 3600)
        days, hours = divmod(hours, 24)
        minutes, _ = divmod(remainder, 60)
        return f"{days}d {hours}h {minutes}m"
    except Exception:
        return "Unknown"


# --------------------------------------------------------------------------
# CPU frequency
# --------------------------------------------------------------------------

def get_cpu_frequency_str():
    try:
        freq = psutil.cpu_freq()
        if not freq:
            return "Unknown"
        if freq.max:
            return f"{freq.current / 1000:.2f} GHz (max {freq.max / 1000:.2f} GHz)"
        return f"{freq.current / 1000:.2f} GHz"
    except Exception:
        return "Unknown"


# --------------------------------------------------------------------------
# Top-level: gather everything the UI / PDF need
# --------------------------------------------------------------------------

def gather_system_specs():
    """
    Returns (specs: dict, disk_info: list[dict], ram_modules: list[dict])
    """
    try:
        cpu_info = cpuinfo.get_cpu_info()
        cpu_name = cpu_info.get("brand_raw") or platform.processor() or "Unknown CPU"
    except Exception:
        cpu_name = platform.processor() or "Unknown CPU"

    os_details = get_os_version_details()
    bios_info = get_bios_info()
    ram_summary = get_ram_summary()
    ram_modules = get_ram_modules()

    specs = {
        "System Platform": os_details["OS Name"],
        "OS Update / Version": os_details["OS Update / Version"],
        "OS Build": os_details["OS Build"],
        "Architecture": platform.machine(),
        "Computer Name": platform.node(),
        "Processor (CPU)": cpu_name,
        "CPU Frequency": get_cpu_frequency_str(),
        "Physical Cores": str(psutil.cpu_count(logical=False)),
        "Logical Cores": str(psutil.cpu_count(logical=True)),
        "Motherboard": get_motherboard_info(),
        "BIOS / Firmware": bios_info,
        "Graphics (GPU)": get_gpu_info(),
    }
    specs.update(ram_summary)
    specs["System Uptime"] = get_uptime_str()

    partitions = psutil.disk_partitions(all=False)
    disk_info = []
    for partition in partitions:
        try:
            usage = psutil.disk_usage(partition.mountpoint)
            disk_info.append({
                "Device": partition.device,
                "Mountpoint": partition.mountpoint,
                "Total": get_size(usage.total),
                "Used": get_size(usage.used),
                "Free": get_size(usage.free),
                "Percentage": f"{usage.percent}%",
            })
        except PermissionError:
            continue

    return specs, disk_info, ram_modules
