import structlog
from pathlib import Path
from docling_graph import run_pipeline, PipelineContext
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.pipeline_options import PdfPipelineOptions, AcceleratorOptions, AcceleratorDevice
from docling.datamodel.base_models import InputFormat

from ..config import settings
from ..models import SemanticPayload, Entity, Tag
from . import _patches  # load the monkey patches

logger = structlog.get_logger(__name__)


class DummyContext:
    def __init__(self, models):
        self.extracted_models = models

def process_document_fast(file_path: Path) -> DummyContext:
    """Uses Docling with GPU mode and raw OpenAI call for lightning-fast extraction."""
    import time, json
    from openai import OpenAI
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.datamodel.accelerator_options import AcceleratorOptions, AcceleratorDevice
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling.datamodel.base_models import InputFormat
    from ..models import Entity, Tag

    logger.info("processing_document_fast", file=file_path.name)
    start_time = time.time()
    
    # 1. GPU Accelerated Docling Conversion
    logger.info("Initializing Docling with Apple Silicon (MPS) GPU acceleration...")
    pipeline_options = PdfPipelineOptions()
    pipeline_options.accelerator_options = AcceleratorOptions(num_threads=8, device=AcceleratorDevice.MPS)
    converter = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)})
    
    try:
        # Extract only the first 5 pages to drastically speed up conversion
        result = converter.convert(file_path, page_range=(1, 5))
        markdown_text = result.document.export_to_markdown()[:16000]
    except Exception as e:
        logger.debug("docling_conversion_failed", file=file_path.name, error=str(e))
        return DummyContext([])
        
    # 2. LLM Tagging
    client = OpenAI(base_url=settings.llm.base_url, api_key=settings.llm.api_key)
    prompt = f"""You are a smart file organizer. Read the following text from the beginning of a document and extract:
1. A 1-sentence summary of what this document is.
2. A list of 3-5 broad tags (e.g., Finance, Toronto, Annual Report) to help categorize this file.
3. A list of 2-5 key entities (e.g., People, Organizations, Locations) mentioned in the document.
Output ONLY a raw JSON object (without markdown code blocks). It must have this exact format:
{{"summary": "...", "tags": ["...", "..."], "entities": [{{"name": "...", "type": "Organization"}}]}}
Document Text:\n{markdown_text}"""
    
    try:
        response = client.chat.completions.create(model=settings.llm.fast_extraction_model, messages=[{"role": "user", "content": prompt}], temperature=0.1)
        json_str = response.choices[0].message.content.strip()
        if json_str.startswith("```json"): json_str = json_str[7:]
        if json_str.endswith("```"): json_str = json_str[:-3]
        data = json.loads(json_str)
        
        payload = SemanticPayload(
            summary=data.get("summary", ""),
            tags=[Tag(name=t) for t in data.get("tags", [])],
            entities=[Entity(name=e.get("name", ""), type=e.get("type", "")) for e in data.get("entities", [])],
            confidence=1.0
        )
        logger.info("extraction_complete", file=file_path.name, duration_seconds=round(time.time() - start_time, 2))
        return DummyContext([payload])
    except Exception as e:
        logger.error("llm_extraction_failed", file=file_path.name, error=str(e))
        return DummyContext([])

def process_document_auto(file_path: Path) -> DummyContext:
    """Dynamically reads pages in blocks of 5, extracting entities, and uses an Orchestrator to early-stop."""
    import time, json
    from openai import OpenAI
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.datamodel.accelerator_options import AcceleratorOptions, AcceleratorDevice
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling.datamodel.base_models import InputFormat
    from ..models import Entity, Tag, SemanticPayload
    
    logger.info("starting_auto_orchestrator", file=file_path.name)
    client = OpenAI(base_url=settings.llm.base_url, api_key=settings.llm.api_key)
    
    pipeline_options = PdfPipelineOptions()
    pipeline_options.accelerator_options = AcceleratorOptions(num_threads=8, device=AcceleratorDevice.MPS)
    converter = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)})
    
    all_entities = []
    all_tags = []
    summary = ""
    
    # Process up to 50 pages (10 blocks of 5)
    for i in range(10):
        start_page = i * 5 + 1
        end_page = start_page + 4
        logger.info(f"Extracting pages {start_page}-{end_page}...")
        
        try:
            result = converter.convert(file_path, page_range=(start_page, end_page))
            markdown_text = result.document.export_to_markdown()
            if not markdown_text.strip():
                logger.info("reached_end_of_document")
                break
        except Exception as e:
            # Docling throws an error if we ask for a page beyond the document's end
            if "fewer than the requested page_range" in str(e):
                logger.debug("reached_end_of_document", pages_processed=start_page-1)
                break
            logger.debug("docling_conversion_failed", file=file_path.name, error=str(e))
            break
            
        # 1. Deep Extraction (12B)
        prompt = f"""Extract keywords from this document section. Return a raw JSON object: {{"summary": "...", "tags": ["...", "..."], "entities": [{{"name": "...", "type": "Organization"}}]}}\nText:\n{markdown_text[:16000]}"""
        
        try:
            response = client.chat.completions.create(model=settings.llm.graph_extraction_model, messages=[{"role": "user", "content": prompt}], temperature=0.1)
            json_str = response.choices[0].message.content.strip()
            if json_str.startswith("```json"): json_str = json_str[7:]
            if json_str.endswith("```"): json_str = json_str[:-3]
            data = json.loads(json_str)
            
            if not summary: summary = data.get("summary", "")
            
            for t in data.get("tags", []):
                if t not in all_tags: all_tags.append(t)
            for e in data.get("entities", []):
                if not any(existing.name == e.get("name") for existing in all_entities):
                    all_entities.append(Entity(name=e.get("name", ""), type=e.get("type", "")))
        except Exception as e:
            logger.error("12b_extraction_failed", error=str(e))
            continue
            
        # 2. Orchestrator Evaluation (4B)
        eval_prompt = f"""You are the Orchestrator AI for a Semantic File Organizer. Your only job is to decide if we have extracted enough semantic keywords to confidently sort and categorize this document.
Filename: "{file_path.name}"
Entities Extracted: {[e.name for e in all_entities]}
Tags Extracted: {all_tags}

Goal: Do we know exactly what this document is? 
- If YES (we have highly specific entities/tags like "Toronto", "Sinking Funds", "2024 Audit"), output {{"stop": true}}. 
- If NO (the keywords are still too generic, vague, or missing), output {{"stop": false}}.
Return ONLY raw JSON."""

        try:
            eval_response = client.chat.completions.create(model=settings.llm.clustering_model, messages=[{"role": "user", "content": eval_prompt}], temperature=0.1)
            eval_str = eval_response.choices[0].message.content.strip()
            if eval_str.startswith("```json"): eval_str = eval_str[7:]
            if eval_str.endswith("```"): eval_str = eval_str[:-3]
            decision = json.loads(eval_str)
            
            if decision.get("stop") == True:
                logger.info("orchestrator_halted_extraction", reason="Sufficient semantic context reached", pages_processed=end_page)
                break
            else:
                logger.info("orchestrator_requested_more_context", pages_processed=end_page)
        except Exception as e:
            logger.error("orchestrator_evaluation_failed", error=str(e))
            
    payload = SemanticPayload(summary=summary, tags=[Tag(name=t) for t in all_tags], entities=all_entities, confidence=1.0)
    return DummyContext([payload])

def process_document(file_path: Path, method: str = "graph") -> PipelineContext:
    if method == "fast":
        return process_document_fast(file_path)
    elif method == "auto":
        return process_document_auto(file_path)
        
    """Uses docling-graph to parse and analyze the document in one pass."""
    logger.debug("processing_document_with_docling_graph", file_path=str(file_path))
    
    config = {
        "source": str(file_path),
        "template": SemanticPayload,
        "backend": "llm",
        "inference": "remote",
        "processing_mode": "many-to-one",
        "extraction_contract": "auto",  # Use chunking for big files, direct for small
        "provider_override": "openai", 
        "model_override": f"openai/{settings.llm.graph_extraction_model}", 
        "structured_output": True,
        "use_chunking": True,
        "chunker_config": {
            "chunk_max_tokens": 500
        },
        "gleaning_enabled": False,
        "dense_dedupe": "off",
        "dense_fill_nodes_cap": 10,
        "llm_overrides": {
            "connection": {
                "api_key": settings.llm.api_key or "lm-studio",
                "base_url": settings.llm.base_url
            },
            "reliability": {
                "timeout_s": 3600
            },
            "generation": {
                "max_tokens": 2048
            },
            "context_limit": 16384
        }
    }
    
    context = run_pipeline(config)
    return context
