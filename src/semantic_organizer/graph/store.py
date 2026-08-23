import json
import os
import structlog
from pathlib import Path
import networkx as nx

from ..models import OSMetadata

logger = structlog.get_logger(__name__)

class GraphManager:
    def __init__(self, target_dir: Path):
        self.target_dir = Path(target_dir)
        self.graph_path = self.target_dir / ".semantic_graph.json"
        self.graph = nx.Graph()
        self._load_graph()
        
    def _load_graph(self):
        if self.graph_path.exists():
            try:
                with open(self.graph_path, 'r') as f:
                    data = json.load(f)
                    self.graph = nx.node_link_graph(data)
                logger.info("graph_loaded", nodes=self.graph.number_of_nodes(), edges=self.graph.number_of_edges())
            except Exception as e:
                logger.error("graph_load_failed", error=str(e))
                
    def _save_graph(self):
        self.target_dir.mkdir(parents=True, exist_ok=True)
        data = nx.node_link_data(self.graph)
        with open(self.graph_path, 'w') as f:
            json.dump(data, f, indent=2)

    def wipe_db(self):
        previous_count = self.graph.number_of_nodes()
        self.graph.clear()
        self._save_graph()
        logger.debug("graph_cleared", previous_nodes=previous_count)
        return previous_count

    def upsert_document_graph(self, context, file_path: Path):
        from ..extraction.parser import compute_file_hash
        
        if not context.extracted_models:
            return False
            
        payload = context.extracted_models[0]
        content_hash = compute_file_hash(file_path)
        doc_id = f"sha256:{content_hash}"
        
        stat = file_path.stat()
        os_metadata = {
            "size_bytes": stat.st_size,
            "last_accessed": stat.st_atime,
            "last_modified": stat.st_mtime,
            "original_folder": file_path.parent.name
        }
        
        # Add Document Node
        self.graph.add_node(doc_id, 
            type="Document",
            path=str(file_path),
            filename=file_path.name,
            extension=file_path.suffix,
            summary=getattr(payload, "summary", ""),
            **os_metadata
        )
        
        # Add Folder Node
        folder_id = f"folder:{os_metadata['original_folder']}"
        self.graph.add_node(folder_id, type="Folder", name=os_metadata['original_folder'])
        self.graph.add_edge(doc_id, folder_id, type="LOCATED_IN")
        
        # Add Tags
        for tag in getattr(payload, "tags", []):
            tag_name = getattr(tag, "name", tag) if not isinstance(tag, (str, dict)) else (tag.get("name", tag) if isinstance(tag, dict) else tag)
            if tag_name:
                tid = f"tag:{tag_name.lower().strip()}"
                self.graph.add_node(tid, type="Tag", name=tag_name)
                self.graph.add_edge(doc_id, tid, type="TAGGED_AS")
                
        # Add Entities
        for entity in getattr(payload, "entities", []):
            if isinstance(entity, dict):
                name = entity.get("name", "")
                ent_type = entity.get("type", "Unknown")
            else:
                name = getattr(entity, "name", "")
                ent_type = getattr(entity, "type", "Unknown")
            if name:
                eid = f"entity:{ent_type}:{name.lower().strip()}"
                self.graph.add_node(eid, type="Entity", name=name, entity_type=ent_type)
                self.graph.add_edge(doc_id, eid, type="MENTIONS")
                
        self._save_graph()
        return False
