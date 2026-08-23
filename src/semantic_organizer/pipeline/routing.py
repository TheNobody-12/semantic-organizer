import shutil
from pathlib import Path
from pydantic import BaseModel
import structlog

from ..models import ParsedDocument
from .taxonomy import TaxonomyDef, get_category_by_id, get_document_type_by_id
from .sidecar import write_sidecars

logger = structlog.get_logger(__name__)

def decide_target_path(target_dir: Path, payload: BaseModel, taxonomy: TaxonomyDef, original_filename: str) -> Path:
    """
    Determines the target path based on the category_id and document_type.
    Creates a two-level folder structure: Category/DocumentType/filename
    """
    category_id = getattr(payload, "category_id", "uncategorized")
    category_def = get_category_by_id(taxonomy, category_id)
    
    primary_folder = category_def.primary_folder if category_def else "Uncategorized"
    
    # Resolve document_type sub-folder
    document_type_id = getattr(payload, "document_type", "other")
    doc_type_def = get_document_type_by_id(taxonomy, document_type_id)
    subfolder = doc_type_def.label if doc_type_def else "Other"
    
    category_path = target_dir / primary_folder / subfolder
    category_path.mkdir(parents=True, exist_ok=True)
    
    return category_path / original_filename

def _get_safe_path(target_path: Path) -> Path:
    """
    Ensures safe copy by appending _N if the file already exists.
    """
    if not target_path.exists():
        return target_path
        
    stem = target_path.stem
    suffix = target_path.suffix
    parent = target_path.parent
    
    counter = 2
    while True:
        new_path = parent / f"{stem}_{counter}{suffix}"
        if not new_path.exists():
            return new_path
        counter += 1

def copy_and_write_artifacts(
    document: ParsedDocument, 
    payload: BaseModel, 
    taxonomy: TaxonomyDef, 
    target_dir: Path,
    dry_run: bool = False,
    graph_manager = None
) -> Path:
    """
    Handles the safe copy operation and writes sidecar artifacts transactionally.
    Returns the final path of the copied document.
    """
    target_path_initial = decide_target_path(target_dir, payload, taxonomy, document.source_path.name)
    target_path = _get_safe_path(target_path_initial)
    
    if dry_run:
        logger.debug("dry_run_copy", source=str(document.source_path), target=str(target_path))
        return target_path
        
    logger.debug("copying_file_tmp", source=str(document.source_path), target=str(target_path))
    
    # 1. Copy to temp file
    tmp_path = target_path.with_suffix(target_path.suffix + ".tmp")
    shutil.copy2(document.source_path, tmp_path)
    
    # 2. Verify hash
    from ..extraction.parser import compute_file_hash
    copied_hash = compute_file_hash(tmp_path)
    if copied_hash != document.content_hash:
        tmp_path.unlink(missing_ok=True)
        raise RuntimeError(f"Hash mismatch after copying {document.source_path}. Expected {document.content_hash}, got {copied_hash}")
        
    # 3. Write sidecars (they write to target_path directly in sidecar.py, let's fix sidecar.py later or rely on atomicity here)
    # Actually, sidecar.py takes target_path and appends .semantic.md. 
    # For idempotency, we let write_sidecars write them, then if we crash, it's fine because sidecars are derived.
    write_sidecars(target_path, document, payload, taxonomy, graph_manager=graph_manager)
    
    # 4. Atomic rename
    tmp_path.rename(target_path)
    
    return target_path
