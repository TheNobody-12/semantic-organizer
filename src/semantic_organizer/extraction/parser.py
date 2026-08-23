import hashlib
from pathlib import Path
import structlog

from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.chunking import HybridChunker

from ..models import ParsedDocument, DocumentChunk

logger = structlog.get_logger(__name__)

def compute_file_hash(file_path: Path) -> str:
    """Compute SHA-256 hash of a file's content."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            sha256.update(chunk)
    return sha256.hexdigest()

def get_converter() -> DocumentConverter:
    """Initialize a DocumentConverter with speed-optimized settings for MVP."""
    pipeline_options = PdfPipelineOptions()
    pipeline_options.do_ocr = False
    pipeline_options.do_table_structure = False
    
    return DocumentConverter(
        allowed_formats=[InputFormat.PDF, InputFormat.DOCX, InputFormat.PPTX, InputFormat.XLSX, InputFormat.HTML, InputFormat.MD],
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
        }
    )

def extract_text(file_path: Path, converter: DocumentConverter | None = None) -> ParsedDocument:
    """Extracts text from a file and returns a ParsedDocument with semantic chunks."""
    if converter is None:
        converter = get_converter()
        
    logger.debug("parsing_document", file=str(file_path))
    content_hash = compute_file_hash(file_path)
    document_id = f"sha256:{content_hash}"
    
    try:
        result = converter.convert(file_path)
        markdown = result.document.export_to_markdown()
        pages = None
        if hasattr(result.document, "pages"):
            pages = len(result.document.pages)
            
        # Create Chunks
        chunker = HybridChunker()
        doc_chunks = []
        for i, raw_chunk in enumerate(chunker.chunk(result.document)):
            # If contextualize exists, it returns a string in docling 2.0+
            if hasattr(chunker, 'contextualize'):
                ctx = chunker.contextualize(raw_chunk)
                text = ctx.text if hasattr(ctx, 'text') else ctx
            else:
                text = getattr(raw_chunk, 'text', '')
            
            # Basic metadata extraction if available
            meta = {}
            if hasattr(raw_chunk, 'meta'):
                if hasattr(raw_chunk.meta, 'headings') and raw_chunk.meta.headings:
                    meta['headings'] = raw_chunk.meta.headings
            
            doc_chunks.append(DocumentChunk(
                chunk_index=i,
                text=text,
                metadata=meta
            ))
            
        return ParsedDocument(
            document_id=document_id,
            source_path=file_path,
            markdown=markdown,
            pages=pages,
            content_hash=content_hash,
            chunks=doc_chunks
        )
    except Exception as e:
        logger.error("parsing_failed", file=str(file_path), error=str(e))
        raise
