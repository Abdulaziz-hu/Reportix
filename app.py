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

def get_gpu_info():
    gpus = []
    system = platform.system()
    
    if GPUtil:
        try:
            gpus_found = GPUtil.getGPUs()
            for gpu in gpus_found:
                gpus.append(f"{gpu.name} ({get_size(gpu.memoryTotal * 1024 * 1024, 'B')} VRAM)")
        except Exception:
            pass

    if not gpus and system == "Windows":
        try:
            cmd = "powershell -Command \"Get-WmiObject Win32_VideoController | Select-Object Name | Format-List\""
            output = subprocess.check_output(cmd, shell=True, text=True, errors="ignore")
            for line in output.split('\n'):
                if "Name" in line and ":" in line:
                    gpu_name = line.split(":", 1)[1].strip()
                    if gpu_name and gpu_name not in gpus:
                        gpus.append(gpu_name)
        except Exception:
            pass

    if not gpus and system == "Linux":
        try:
            output = subprocess.check_output("lspci | grep -i vga", shell=True, text=True, errors="ignore")
            for line in output.split('\n'):
                if line.strip():
                    gpus.append(line.split(':')[-1].strip())
        except Exception:
            pass

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

    story.append(Paragraph("Reportix - System Specifications & PDF Reporter", title_style))
    story.append(Paragraph(f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles['Normal']))
    story.append(Spacer(1, 10))

    story.append(Paragraph("Hardware & OS Overview", section_style))
    spec_data = [[Paragraph(f"<b>{k}</b>", styles['Normal']), Paragraph(str(v), styles['Normal'])] for k, v in specs.items()]
    t1 = Table(spec_data, colWidths=[180, 360])
    t1.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#F7FAFC")),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#E2E8F0")),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('PADDING', (0,0), (-1,-1), 5),
    ]))
    story.append(t1)
    story.append(Spacer(1, 10))

    story.append(Paragraph("Storage Partitions", section_style))
    disk_table_data = [["Device", "Mount", "Total", "Used", "Free", "Use %"]]
    for d in disk_info:
        disk_table_data.append([d["Device"], d["Mountpoint"], d["Total"], d["Used"], d["Free"], d["Percentage"]])
    
    t2 = Table(disk_table_data, colWidths=[100, 100, 80, 80, 80, 100])
    t2.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#2B6CB0")),
        ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#E2E8F0")),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('PADDING', (0,0), (-1,-1), 5),
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