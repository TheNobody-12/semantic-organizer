import json
from pathlib import Path
from pydantic import BaseModel
import structlog

from ..models import ParsedDocument
from .taxonomy import TaxonomyDef, get_category_by_id, get_document_type_by_id

logger = structlog.get_logger(__name__)

def _format_wikilink(text: str) -> str:
    """Formats text as an Obsidian WikiLink, removing illegal characters."""
    clean_text = str(text).replace("[", "").replace("]", "").replace("|", "-")
    return f"[[{clean_text}]]"

def write_sidecars(target_file_path: Path, document: ParsedDocument, payload: BaseModel, taxonomy: TaxonomyDef, graph_manager=None):
    """
    Writes .semantic.json and .semantic.md sidecar artifacts next to the copied file.
    """
    logger.debug("writing_sidecars", target=str(target_file_path))
    
    # 1. JSON Sidecar
    json_path = target_file_path.with_suffix(target_file_path.suffix + ".semantic.json")
    
    payload_dict = payload.model_dump()
    payload_dict["document_id"] = document.document_id
    payload_dict["original_path"] = str(document.source_path)
    payload_dict["content_hash"] = document.content_hash
    
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload_dict, f, indent=2)
        
    # 2. Markdown Sidecar
    md_path = target_file_path.with_suffix(target_file_path.suffix + ".semantic.md")
    
    category_id = payload_dict.get("category_id", "uncategorized")
    category_def = get_category_by_id(taxonomy, category_id)
    category_label = category_def.label if category_def else category_id
    
    document_type_id = payload_dict.get("document_type", "other")
    doc_type_def = get_document_type_by_id(taxonomy, document_type_id)
    document_type_label = doc_type_def.label if doc_type_def else document_type_id
    
    # Generate Namespaced YAML Frontmatter
    frontmatter = ["---"]
    frontmatter.append("semantic:")
    frontmatter.append(f"  category: \"{category_label}\"")
    frontmatter.append(f"  document_type: \"{document_type_label}\"")
    frontmatter.append(f"  confidence: {payload_dict.get('confidence', 0.0):.2f}")
    frontmatter.append(f"  hash: \"{document.content_hash}\"")
    frontmatter.append(f"  original_path: \"{document.source_path}\"")
    
    tags = payload_dict.get("tags", [])
    if tags:
        frontmatter.append("  tags:")
        for tag in tags:
            tag_name = tag.get("name", tag) if isinstance(tag, dict) else tag
            frontmatter.append(f"    - \"{tag_name}\"")
            
    entities = payload_dict.get("entities", [])
    if entities:
        frontmatter.append("  entities:")
        for e in entities:
            frontmatter.append(f"    - name: \"{e['name']}\"")
            frontmatter.append(f"      type: \"{e['type']}\"")
            
    frontmatter.append("---")
    
    # Markdown Body
    entities_list = "\n".join([f"- {_format_wikilink(e['name'])} ({e['type']})" for e in entities])
    tags_list = " ".join([f"#{t.get('name', t).replace(' ', '_')}" if isinstance(t, dict) else f"#{t.replace(' ', '_')}" for t in tags])
    
    md_lines = list(frontmatter)
    md_lines.append(f"\n# {document.source_path.name}")
    md_lines.append(f"\n[Open Original Document](./{target_file_path.name})")
    
    md_lines.append(f"\n## Summary\n{payload_dict.get('summary', '')}")
    
    md_lines.append(f"\n## Tags\n{tags_list if tags_list else 'None'}")
    md_lines.append(f"\n## Entities\n{entities_list if entities_list else 'None'}")
    
    # 3. Dynamic Graph Related Documents
    if graph_manager:
        related_paths = graph_manager.find_related_documents(document.document_id, limit=5)
        if related_paths:
            md_lines.append("\n## Graph Related Documents")
            md_lines.append("> Dynamically discovered via shared entities and tags in Neo4j.\n")
            for path in related_paths:
                # We extract just the filename for the wikilink to look nice
                filename = Path(path).name
                md_lines.append(f"- {_format_wikilink(filename)}")
                
    md_lines.append("\n## Dataview Notes")
    md_lines.append("```dataview")
    md_lines.append("LIST")
    md_lines.append("WHERE contains(semantic.tags, this.semantic.tags[0])")
    md_lines.append("AND file.name != this.file.name")
    md_lines.append("```")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines) + "\n")
