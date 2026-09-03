import os
from datetime import datetime

from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch

from .version import APP_NAME, APP_VERSION

FOOTER_COLOR = colors.HexColor("#94A3B8")


def _draw_footer(canvas, doc):
    """Stamped on every page: app name + version on the left, page number
    on the right, so an exported report is always traceable back to the
    Reportix build that produced it."""
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(FOOTER_COLOR)
    canvas.drawString(36, 24, f"{APP_NAME} v{APP_VERSION}")
    canvas.drawRightString(letter[0] - 36, 24, f"Page {doc.page}")
    canvas.restoreState()


def generate_pdf(specs, disk_info, ram_modules=None, filename="Reportix_System_Report.pdf"):
    ram_modules = ram_modules or []

    doc = SimpleDocTemplate(
        filename, pagesize=letter,
        rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=48,
    )
    story = []
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        'TitleStyle', parent=styles['Heading1'], fontSize=18,
        textColor=colors.HexColor("#1A202C"), spaceAfter=4,
    )
    subtitle_style = ParagraphStyle(
        'SubtitleStyle', parent=styles['Normal'], fontSize=9,
        textColor=colors.HexColor("#718096"),
    )
    section_style = ParagraphStyle(
        'SectionStyle', parent=styles['Heading2'], fontSize=13,
        textColor=colors.HexColor("#2B6CB0"), spaceBefore=10, spaceAfter=6,
    )
    note_style = ParagraphStyle(
        'NoteStyle', parent=styles['Normal'], fontSize=8.5,
        textColor=colors.HexColor("#718096"), spaceBefore=4,
    )
    # Dedicated cell styles for the tables. Plain strings inside a Table
    # never wrap - if a value (e.g. a long GPU string) is wider than its
    # column, ReportLab lets it overflow and paint over neighboring
    # columns. Wrapping every cell in a Paragraph forces proper
    # word-wrapping inside the column instead.
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
    ram_cell_style = ParagraphStyle(
        'RamCellStyle', parent=cell_style, fontSize=8, leading=10, wordWrap='CJK'
    )

    story.append(Paragraph("Reportix - System Specifications & PDF Reporter", title_style))
    story.append(Paragraph(
        f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} "
        f"&nbsp;&middot;&nbsp; Reportix v{APP_VERSION}",
        subtitle_style,
    ))
    story.append(Spacer(1, 10))

    # --- Hardware & OS overview -------------------------------------------------
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

    # --- RAM modules --------------------------------------------------------
    story.append(Paragraph("Memory (RAM) Modules", section_style))
    if ram_modules:
        ram_table_data = [
            [Paragraph(h, header_style) for h in
             ["Slot", "Manufacturer", "Part Number", "Capacity", "Speed"]]
        ]
        for m in ram_modules:
            ram_table_data.append([
                Paragraph(str(m.get("Slot", "N/A")), ram_cell_style),
                Paragraph(str(m.get("Manufacturer", "Unknown")), ram_cell_style),
                Paragraph(str(m.get("Part Number", "Unknown")), ram_cell_style),
                Paragraph(str(m.get("Capacity", "Unknown")), ram_cell_style),
                Paragraph(str(m.get("Speed", "Unknown")), ram_cell_style),
            ])
        t_ram = Table(ram_table_data, colWidths=[70, 140, 140, 90, 100], repeatRows=1)
        t_ram.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#2B6CB0")),
            ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#E2E8F0")),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('LEFTPADDING', (0,0), (-1,-1), 5),
            ('RIGHTPADDING', (0,0), (-1,-1), 5),
            ('TOPPADDING', (0,0), (-1,-1), 4),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor("#F7FAFC")]),
        ]))
        story.append(t_ram)
    else:
        story.append(Paragraph(
            "Per-module memory details (brand, part number, speed) could not be "
            "detected on this system. On Linux this typically requires running "
            "with elevated privileges (e.g. via 'sudo') since it relies on "
            "'dmidecode'.",
            note_style,
        ))
    story.append(Spacer(1, 10))

    # --- Storage partitions --------------------------------------------------
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

    doc.build(story, onFirstPage=_draw_footer, onLaterPages=_draw_footer)
    return os.path.abspath(filename)
