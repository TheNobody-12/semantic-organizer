from pathlib import Path
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.datamodel.base_models import InputFormat
from reportlab.pdfgen import canvas

c = canvas.Canvas("dummy.pdf")
c.drawString(100, 100, "Hello World")
c.save()

pipeline_options = PdfPipelineOptions()
converter = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)})

try:
    result = converter.convert(Path("dummy.pdf"), page_range=(1, 5))
    print("SUCCESS")
except Exception as e:
    print("FAILED:", str(e))
