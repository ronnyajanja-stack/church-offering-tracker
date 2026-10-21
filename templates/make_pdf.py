from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

pdf_path = "REGISTRY_MEMORANDUM.pdf"
doc = SimpleDocTemplate(
    pdf_path,
    pagesize=letter,
    rightMargin=45,
    leftMargin=45,
    topMargin=45,
    bottomMargin=45
)

styles = getSampleStyleSheet()

header_style = ParagraphStyle(
    'InstHeader',
    parent=styles['Heading1'],
    fontSize=13,
    leading=16,
    alignment=1,
    fontName="Helvetica-Bold",
    textColor=colors.HexColor("#1A2B4C")
)

sub_header_style = ParagraphStyle(
    'MemoTitle',
    parent=styles['Heading2'],
    fontSize=12,
    leading=14,
    alignment=1,
    fontName="Helvetica-Bold",
    textColor=colors.HexColor("#333333")
)

body_style = ParagraphStyle(
    'Body',
    parent=styles['Normal'],
    fontSize=9.5,
    leading=14,
    fontName="Helvetica",
    textColor=colors.HexColor("#222222")
)

section_heading = ParagraphStyle(
    'SectionHead',
    parent=styles['Heading3'],
    fontSize=10.5,
    leading=14,
    fontName="Helvetica-Bold",
    textColor=colors.HexColor("#1A2B4C")
)

bullet_style = ParagraphStyle(
    'Bullet',
    parent=body_style,
    leftIndent=15,
    firstLineIndent=-10
)

story = []

# Institutional Header
story.append(Paragraph("KENYA MEDICAL LABORATORY TECHNICIANS AND TECHNOLOGISTS BOARD", header_style))
story.append(Spacer(1, 4))
story.append(Paragraph("INTERNAL MEMORANDUM", sub_header_style))
story.append(Spacer(1, 10))
story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#1A2B4C"), spaceAfter=12))

# Metadata Table
meta_data = [
    [Paragraph("<b>TO:</b>", body_style), Paragraph("The Registrar", body_style)],
    [Paragraph("<b>FROM:</b>", body_style), Paragraph("Ronny Ajanja (Registry Department)", body_style)],
    [Paragraph("<b>DATE:</b>", body_style), Paragraph("11th September, 2026", body_style)],
    [Paragraph("<b>SUBJECT:</b>", body_style), Paragraph("<b>REQUEST FOR ADDITIONAL HUMAN RESOURCE ALLOCATION IN REGISTRY</b>", body_style)],
]

t = Table(meta_data, colWidths=[65, 455])
t.setStyle(TableStyle([
    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ('TOPPADDING', (0, 0), (-1, -1), 3),
    ('LEFTPADDING', (0, 0), (-1, -1), 0),
    ('RIGHTPADDING', (0, 0), (-1, -1), 0),
]))
story.append(t)
story.append(Spacer(1, 8))
story.append(HRFlowable(width="100%", thickness=0.8, color=colors.HexColor("#CCCCCC"), spaceAfter=12))

# 1. Purpose
story.append(Paragraph("1. Purpose", section_heading))
story.append(Spacer(1, 3))
story.append(Paragraph(
    "The purpose of this memorandum is to formally request the allocation of additional personnel to the "
    "Registry Department following the transfer of Mr. Kevin Owako to the Finance Department. Additional support "
    "is necessary to maintain continuous registry operations, eliminate retrieval delays, and manage ongoing "
    "clerical demands.",
    body_style
))
story.append(Spacer(1, 9))

# 2. Operational Workload
story.append(Paragraph("2. Operational Workload and Capacity Justification", section_heading))
story.append(Spacer(1, 3))
story.append(Paragraph(
    "Registry operations require continuous manual handling and strict records tracking. With the department "
    "currently manned by a single officer, key daily responsibilities include:",
    body_style
))
story.append(Spacer(1, 5))

tasks = [
    "<b>File Circulation & Tracking:</b> Promptly retrieving physical files upon requisition, updating checkout entries on the online file tracking system, verifying returned records, and reshelving them in their designated locations.",
    "<b>Receipting & Filing:</b> Regularly filing and attaching incoming payment receipts into practitioners' physical files as client renewals and new registrations occur.",
    "<b>New File Registration:</b> Indexing and capturing new member registration files into the registry database upon receipt.",
    "<b>Physical Archive Upkeep:</b> Maintaining the physical condition of member files, organizing storage racks, and handling bulk archive boxes.",
    "<b>Process Improvement:</b> Actively formulating workflow recommendations and developing structured proposals toward the Board's long-term registry modernization and digitization goals."
]

for task in tasks:
    story.append(Paragraph(f"• &nbsp; {task}", bullet_style))
    story.append(Spacer(1, 3))

story.append(Spacer(1, 4))
story.append(Paragraph(
    "Given the ongoing volume of client renewals, new registrations, and daily inter-departmental file requisitions, "
    "running registry operations with one officer risks operational backlogs and extended turnaround times.",
    body_style
))
story.append(Spacer(1, 9))

# 3. Proposed Solutions
story.append(Paragraph("3. Proposed Solutions", section_heading))
story.append(Spacer(1, 3))
story.append(Paragraph(
    "To address this staffing deficit, I respectfully present the following options for your guidance and consideration:",
    body_style
))
story.append(Spacer(1, 5))

proposals = [
    "<b>Dedicated Reassignment of an Intern:</b> Assign an intern to the Registry Department on a dedicated basis to support daily operations. Because the role entails heavy manual handling—including lifting high-density archive boxes, shelf re-arrangements, and bulk receipt binding—allocating personnel suited for labor-intensive physical tasks will ensure smooth operations.",
    "<b>Engagement of Registry Support Staff:</b> Alternatively, consider engaging an additional staff member to fill the operational gap left in the department."
]

for idx, prop in enumerate(proposals, 1):
    story.append(Paragraph(f"<b>{idx}.</b> &nbsp; {prop}", bullet_style))
    story.append(Spacer(1, 4))

story.append(Spacer(1, 7))

# 4. Conclusion
story.append(Paragraph("4. Conclusion", section_heading))
story.append(Spacer(1, 3))
story.append(Paragraph(
    "I remain committed to ensuring that Registry operations remain efficient, accurate, and responsive to the Board’s "
    "service delivery needs. Thank you for your continued leadership and consideration of this request. I look forward "
    "to your guidance and direction.",
    body_style
))
story.append(Spacer(1, 14))

# Sign-off
story.append(Paragraph("<b>Ronny Ajanja</b>", body_style))
story.append(Paragraph("Registry Department", body_style))
story.append(Paragraph("<i>Kenya Medical Laboratory Technicians and Technologists Board (KMLTTB)</i>", body_style))

doc.build(story)
print("PDF created successfully as REGISTRY_MEMORANDUM.pdf")