import json
import shutil
import structlog
from pathlib import Path
from typing import Any
from pydantic import BaseModel

from ..graph.store import GraphManager
from .journal import OperationJournal, DocState

logger = structlog.get_logger(__name__)

class OverlapAnalyzer:
    def __init__(self, graph_manager: GraphManager):
        self.graph_manager = graph_manager
        
    def analyze_overlap(self) -> list[dict[str, Any]]:
        query = """
        MATCH (c1:Category)<-[:BELONGS_TO]-(d1:Document)-[:MENTIONS|TAGGED_AS]->(shared)<-[:MENTIONS|TAGGED_AS]-(d2:Document)-[:BELONGS_TO]->(c2:Category)
        WHERE elementId(c1) < elementId(c2)
        RETURN c1.id AS category1, c2.id AS category2, count(DISTINCT shared) AS shared_concepts
        ORDER BY shared_concepts DESC
        LIMIT 10
        """
        with self.graph_manager.driver.session() as session:
            results = session.run(query)
            return [dict(record) for record in results if record["shared_concepts"] > 0]

class MovePlanner:
    def __init__(self, journal: OperationJournal):
        self.journal = journal
        
    def generate_plan(self, current_taxonomy_hash: str, new_taxonomy_hash: str) -> dict[str, str]:
        # In a real scenario, this would use Neo4j to re-map files to a new taxonomy.
        # For Phase 5 demonstration, we will simulate a move plan by just generating
        # a JSON map of current paths to target paths.
        # A true implementation would re-run `analyze_document` on all documents against the new taxonomy.
        pass

class RollbackManager:
    def __init__(self):
        pass
        
    @staticmethod
    def create_manifest(moves: list[tuple[Path, Path]], manifest_path: Path):
        data = [{"source": str(s), "target": str(t)} for s, t in moves]
        with open(manifest_path, "w") as f:
            json.dump(data, f, indent=2)
            
    @staticmethod
    def apply_rollback(manifest_path: Path):
        if not manifest_path.exists():
            raise FileNotFoundError(f"Manifest not found: {manifest_path}")
            
        with open(manifest_path, "r") as f:
            moves = json.load(f)
            
        for move in moves:
            source = Path(move["source"])
            target = Path(move["target"])
            
            if target.exists():
                if not source.parent.exists():
                    source.parent.mkdir(parents=True, exist_ok=True)
                
                shutil.move(str(target), str(source))
                logger.info("rollback_file", target=str(target), restored_to=str(source))
                
                # Also rollback sidecars
                target_sidecar_md = target.with_suffix(target.suffix + ".semantic.md")
                source_sidecar_md = source.with_suffix(source.suffix + ".semantic.md")
                if target_sidecar_md.exists():
                    shutil.move(str(target_sidecar_md), str(source_sidecar_md))
                    
                target_sidecar_json = target.with_suffix(target.suffix + ".semantic.json")
                source_sidecar_json = source.with_suffix(source.suffix + ".semantic.json")
                if target_sidecar_json.exists():
                    shutil.move(str(target_sidecar_json), str(source_sidecar_json))
