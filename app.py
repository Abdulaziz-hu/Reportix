import sys
import os
import platform
import subprocess
import multiprocessing
from datetime import datetime

import psutil
import cpuinfo

try:
    import GPUtil
except ImportError:
    GPUtil = None

from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTextEdit, QLabel, QMessageBox
)

def get_size(bytes, suffix="B"):
    factor = 1024
    for unit in ["", "K", "M", "G", "T", "P"]:
        if bytes < factor:
            return f"{bytes:.2f} {unit}{suffix}"
        bytes /= factor

def get_motherboard_info():
    board = "Unknown Motherboard"
    system = platform.system()
    try:
        if system == "Windows":
            cmd = "powershell -Command \"Get-WmiObject Win32_BaseBoard | Select-Object Manufacturer, Product | Format-List\""
            output = subprocess.check_output(cmd, shell=True, text=True, errors="ignore")
            mfg, prod = "", ""
            for line in output.split('\n'):
                if "Manufacturer" in line:
                    mfg = line.split(":", 1)[1].strip()
                elif "Product" in line:
                    prod = line.split(":", 1)[1].strip()
            if mfg or prod:
                board = f"{mfg} {prod}".strip()
        elif system == "Linux":
            mfg = ""
            prod = ""
            if os.path.exists("/sys/class/dmi/id/board_vendor"):
                with open("/sys/class/dmi/id/board_vendor", "r") as f:
                    mfg = f.read().strip()
            if os.path.exists("/sys/class/dmi/id/board_name"):
                with open("/sys/class/dmi/id/board_name", "r") as f:
                    prod = f.read().strip()
            if mfg or prod:
                board = f"{mfg} {prod}".strip()
    except Exception:
        pass
    return board if board else "Standard Motherboard"

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

    # 2) Call nvidia-smi directly. This covers systems where the driver/tool
    #    is present but the optional GPUtil package isn't installed, or
    #    GPUtil failed to parse its output - this was the actual cause of
    #    VRAM being dropped previously.
    if not gpus:
        try:
            output = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=name,memory.total",
                 "--format=csv,noheader,nounits"],
                text=True, errors="ignore", stderr=subprocess.DEVNULL
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
            cmd = ("powershell -Command \"Get-WmiObject Win32_VideoController | "
                   "Select-Object Name, AdapterRAM | Format-List\"")
            output = subprocess.check_output(cmd, shell=True, text=True, errors="ignore")
            name = ""
            for line in output.split('\n'):
                if "Name" in line and ":" in line:
                    name = line.split(":", 1)[1].strip()
                elif "AdapterRAM" in line and ":" in line:
                    ram_str = line.split(":", 1)[1].strip()
                    vram_suffix = ""
                    try:
                        ram_bytes = int(ram_str)
                        if ram_bytes > 0:
                            vram_suffix = f" ({get_size(ram_bytes)} VRAM)"
                    except ValueError:
                        pass
                    if name:
                        gpus.append(f"{name}{vram_suffix}")
                    name = ""
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

def get_bios_and_os_extras():
    bios = "Unknown BIOS"
    uptime = "Unknown"
    system = platform.system()
    try:
        if system == "Windows":
            cmd = "powershell -Command \"Get-WmiObject Win32_BIOS | Select-Object Manufacturer, SMBIOSBIOSVersion | Format-List\""
            output = subprocess.check_output(cmd, shell=True, text=True, errors="ignore")
            mfg, ver = "", ""
            for line in output.split('\n'):
                if "Manufacturer" in line:
                    mfg = line.split(":", 1)[1].strip()
                elif "SMBIOSBIOSVersion" in line:
                    ver = line.split(":", 1)[1].strip()
            if mfg or ver:
                bios = f"{mfg} {ver}".strip()
        
        boot_time = psutil.boot_time()
        uptime_seconds = datetime.now().timestamp() - boot_time
        hours, remainder = divmod(int(uptime_seconds), 3600)
        days, hours = divmod(hours, 24)
        minutes, _ = divmod(remainder, 60)
        uptime = f"{days}d {hours}h {minutes}m"
    except Exception:
        pass
    return bios, uptime

def gather_system_specs():
    try:
        cpu_info = cpuinfo.get_cpu_info()
        cpu_name = cpu_info.get('brand_raw', platform.processor())
    except Exception:
        cpu_name = platform.processor()

    svmem = psutil.virtual_memory()
    bios_info, uptime = get_bios_and_os_extras()
    
    specs = {
        "System Platform": f"{platform.system()} {platform.release()} ({platform.version()})",
        "Architecture": platform.machine(),
        "Computer Name": platform.node(),
        "Processor (CPU)": cpu_name,
        "Motherboard": get_motherboard_info(),
        "BIOS / Firmware": bios_info,
        "Graphics (GPU)": get_gpu_info(),
        "Physical Cores": str(psutil.cpu_count(logical=False)),
        "Logical Cores": str(psutil.cpu_count(logical=True)),
        "Total RAM": get_size(svmem.total),
        "Available RAM": get_size(svmem.available),
        "RAM Usage": f"{svmem.percent}%",
        "System Uptime": uptime
    }

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
                "Percentage": f"{usage.percent}%"
            })
        except PermissionError:
            continue

    return specs, disk_info

def generate_pdf(specs, disk_info, filename="Reportix_System_Report.pdf"):
    doc = SimpleDocTemplate(filename, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    story = []
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        'TitleStyle', parent=styles['Heading1'], fontSize=18, textColor=colors.HexColor("#1A202C"), spaceAfter=10
    )
    section_style = ParagraphStyle(
        'SectionStyle', parent=styles['Heading2'], fontSize=13, textColor=colors.HexColor("#2B6CB0"), spaceBefore=10, spaceAfter=6
    )
    # Dedicated cell styles for the tables. Plain strings inside a Table
    # never wrap - if a value (e.g. a long GPU string or a long snap
    # mountpoint) is wider than its column, ReportLab just lets it overflow
    # and paint over the neighboring columns, which is what produced the
    # garbled/overlapping text in the report. Wrapping every cell in a
    # Paragraph forces proper word-wrapping inside the column instead.
    cell_style = ParagraphStyle(
        'CellStyle', parent=styles['Normal'], fontSize=9, leading=11, wordWrap='CJK'
    )
    cell_style_bold = ParagraphStyle(
        'CellStyleBold', parent=cell_style, fontName='Helvetica-Bold'
    )
    header_style = ParagraphStyle(
        'HeaderStyle', parent=styles['Normal'], fontSize=9, leading=11,
        textColor=colors.whitesmoke, fontName='Helvetica-Bold', alignment=1
    )
    disk_cell_style = ParagraphStyle(
        'DiskCellStyle', parent=cell_style, fontSize=8, leading=10, wordWrap='CJK'
    )

    story.append(Paragraph("Reportix - System Specifications & PDF Reporter", title_style))
    story.append(Paragraph(f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles['Normal']))
    story.append(Spacer(1, 10))

    story.append(Paragraph("Hardware & OS Overview", section_style))
    spec_data = [
        [Paragraph(k, cell_style_bold), Paragraph(str(v), cell_style)]
        for k, v in specs.items()
    ]
    t1 = Table(spec_data, colWidths=[150, 390])
    t1.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#F7FAFC")),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#E2E8F0")),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('LEFTPADDING', (0,0), (-1,-1), 6),
        ('RIGHTPADDING', (0,0), (-1,-1), 6),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
    ]))
    story.append(t1)
    story.append(Spacer(1, 10))

    story.append(Paragraph("Storage Partitions", section_style))
    disk_table_data = [
        [Paragraph(h, header_style) for h in ["Device", "Mount", "Total", "Used", "Free", "Use %"]]
    ]
    for d in disk_info:
        disk_table_data.append([
            Paragraph(d["Device"], disk_cell_style),
            Paragraph(d["Mountpoint"], disk_cell_style),
            Paragraph(d["Total"], disk_cell_style),
            Paragraph(d["Used"], disk_cell_style),
            Paragraph(d["Free"], disk_cell_style),
            Paragraph(d["Percentage"], disk_cell_style),
        ])

    # Wider Device/Mount columns (these hold long paths like
    # /var/lib/snapd/snap/...) and narrower numeric columns; total still
    # sums to the 540pt usable width (letter width 612 - 36 - 36 margins).
    t2 = Table(disk_table_data, colWidths=[120, 150, 70, 70, 70, 60], repeatRows=1)
    t2.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#2B6CB0")),
        ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
        ('ALIGN', (2,0), (-1,-1), 'CENTER'),
        ('ALIGN', (0,0), (1,-1), 'LEFT'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#E2E8F0")),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('LEFTPADDING', (0,0), (-1,-1), 5),
        ('RIGHTPADDING', (0,0), (-1,-1), 5),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor("#F7FAFC")]),
    ]))
    story.append(t2)

    doc.build(story)
    return os.path.abspath(filename)

class ScanWorker(QThread):
    finished = pyqtSignal(dict, list)
    error = pyqtSignal(str)

    def run(self):
        try:
            specs, disks = gather_system_specs()
            self.finished.emit(specs, disks)
        except Exception as e:
            self.error.emit(str(e))

class PdfWorker(QThread):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, specs, disks):
        super().__init__()
        self.specs = specs
        self.disks = disks

    def run(self):
        try:
            path = generate_pdf(self.specs, self.disks)
            self.finished.emit(path)
        except Exception as e:
            self.error.emit(str(e))

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Reportix - System Specifications & PDF Reporter")
        self.resize(750, 550)
        self.setMinimumSize(600, 450)

        self.specs_data = None
        self.disk_data = None
        self.pdf_path = None
        
        self.scan_worker = None
        self.pdf_worker = None

        self.init_ui()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title_label = QLabel("Reportix - System Specifications & PDF Reporter")
        title_label.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        title_label.setStyleSheet("color: #E2E8F0;")
        layout.addWidget(title_label)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self.btn_scan = QPushButton("Grab Specs")
        self.btn_scan.setMinimumHeight(38)
        self.btn_scan.clicked.connect(self.start_scan)
        btn_layout.addWidget(self.btn_scan)

        self.btn_pdf = QPushButton("Generate PDF Report")
        self.btn_pdf.setMinimumHeight(38)
        self.btn_pdf.setEnabled(False)
        self.btn_pdf.clicked.connect(self.start_pdf_generation)
        btn_layout.addWidget(self.btn_pdf)

        layout.addLayout(btn_layout)

        self.text_output = QTextEdit()
        self.text_output.setReadOnly(True)
        self.text_output.setFont(QFont("JetBrains Mono", 10))
        layout.addWidget(self.text_output)

        self.log("Click 'Grab Specs' to begin hardware scan.")

    def log(self, message):
        self.text_output.append(message)

    def start_scan(self):
        self.text_output.clear()
        self.log("Scanning hardware topology (CPU, Motherboard, BIOS, GPU, RAM, Disks)...")
        self.btn_scan.setEnabled(False)
        self.btn_pdf.setEnabled(False)

        self.scan_worker = ScanWorker()
        self.scan_worker.finished.connect(self.on_scan_finished)
        self.scan_worker.error.connect(self.on_scan_error)
        self.scan_worker.start()

    def on_scan_finished(self, specs, disks):
        self.specs_data = specs
        self.disk_data = disks
        self.btn_scan.setEnabled(True)
        self.btn_pdf.setEnabled(True)

        self.log("=== SYSTEM HARDWARE OVERVIEW ===")
        for k, v in specs.items():
            self.log(f"• <b>{k}:</b> {v}")

        self.log("\n=== STORAGE PARTITIONS ===")
        for d in disks:
            self.log(f"• <b>{d['Device']}</b> ({d['Mountpoint']}) — Total: {d['Total']}, Free: {d['Free']} ({d['Percentage']} used)")

        self.log("\nReady to compile report.")

    def on_scan_error(self, err_msg):
        self.btn_scan.setEnabled(True)
        QMessageBox.critical(self, "Error", f"Failed to gather specs:\n{err_msg}")

    def start_pdf_generation(self):
        self.btn_pdf.setEnabled(False)
        self.log("\nCompiling PDF document...")

        self.pdf_worker = PdfWorker(self.specs_data, self.disk_data)
        self.pdf_worker.finished.connect(self.on_pdf_finished)
        self.pdf_worker.error.connect(self.on_pdf_error)
        self.pdf_worker.start()

    def on_pdf_finished(self, path):
        self.pdf_path = path
        self.btn_pdf.setEnabled(True)
        self.log(f"PDF successfully compiled and saved to: {path}")
        self.open_pdf_file()

    def on_pdf_error(self, err_msg):
        self.btn_pdf.setEnabled(True)
        QMessageBox.critical(self, "Error", f"PDF compilation failed:\n{err_msg}")

    def open_pdf_file(self):
        if not self.pdf_path or not os.path.exists(self.pdf_path):
            return
        try:
            system = platform.system()
            if system == "Windows":
                os.startfile(self.pdf_path)
            elif system == "Darwin":
                subprocess.run(["open", self.pdf_path])
            else:
                subprocess.run(["xdg-open", self.pdf_path])
        except Exception as e:
            QMessageBox.warning(self, "Warning", f"Could not open file automatically: {e}")

def apply_stylesheet(app):
    stylesheet = """
        QMainWindow {
            background-color: #0F172A;
        }
        QLabel {
            color: #F8FAFC;
            font-family: 'Segoe UI', sans-serif;
        }
        QPushButton {
            background-color: #2563EB;
            color: #FFFFFF;
            border-radius: 6px;
            padding: 6px 16px;
            font-family: 'Segoe UI', sans-serif;
            font-weight: bold;
            font-size: 10pt;
            border: none;
        }
        QPushButton:hover {
            background-color: #1D4ED8;
        }
        QPushButton:disabled {
            background-color: #334155;
            color: #64748B;
        }
        QTextEdit {
            background-color: #1E293B;
            color: #E2E8F0;
            border: 1px solid #334155;
            border-radius: 8px;
            padding: 8px;
            selection-background-color: #3B82F6;
        }
    """
    app.setStyleSheet(stylesheet)

if __name__ == "__main__":
    # IMPORTANT: py-cpuinfo (and Python's multiprocessing in general) spawns a
    # separate worker process to safely read CPUID info. When this app is
    # frozen into a single .exe with PyInstaller, sys.executable IS the app
    # itself, so without freeze_support() that worker process re-launches the
    # entire GUI instead of just running the worker function. Calling
    # freeze_support() here lets frozen child processes detect they're a
    # multiprocessing worker and skip straight to doing their job instead of
    # opening a second window.
    multiprocessing.freeze_support()

    app = QApplication(sys.argv)
    apply_stylesheet(app)
    
    window = MainWindow()
    window.show()
    sys.exit(app.exec())