import structlog
import networkx as nx
from networkx.algorithms.community import louvain_communities
from pathlib import Path
from typing import Dict, List, Any
import json

from .store import GraphManager
from ..config import settings
from litellm import completion

logger = structlog.get_logger(__name__)

class ClusteringEngine:
    def __init__(self, graph_manager: GraphManager):
        self.gm = graph_manager
        
    def find_clusters(self) -> List[List[str]]:
        """Run Louvain community detection on a pruned graph to find document clusters."""
        logger.info("running_louvain_community_detection")
        undirected_graph = self.gm.graph.to_undirected()
        
        # --- PRUNING LOGIC ---
        # Remove noisy Tag/Entity nodes that are only connected to ONE document.
        # This forces Louvain to only cluster based on shared connections.
        nodes_to_remove = []
        for node in undirected_graph.nodes():
            if undirected_graph.degree(node) <= 1 and self.gm.graph.nodes[node].get("type") != "Document":
                nodes_to_remove.append(node)
                
        undirected_graph.remove_nodes_from(nodes_to_remove)
        logger.info(f"Pruned {len(nodes_to_remove)} noise nodes for smarter clustering.")
        
        communities = louvain_communities(undirected_graph)
        
        doc_clusters = []
        for community in communities:
            docs_in_community = [n for n in community if self.gm.graph.nodes[n].get("type") == "Document"]
            if docs_in_community:
                doc_clusters.append(docs_in_community)
                
        return doc_clusters

    def name_cluster(self, doc_ids: List[str]) -> str:
        """Use LLM to name a cluster based on its documents, entities, and tags."""
        from openai import OpenAI
        
        entities_count = {}
        tags_count = {}
        doc_names = []
        
        for doc_id in doc_ids:
            doc_node = self.gm.graph.nodes[doc_id]
            doc_names.append(doc_node.get("filename", ""))
            
            for neighbor in self.gm.graph.neighbors(doc_id):
                node = self.gm.graph.nodes[neighbor]
                if node.get("type") == "Entity":
                    name = node.get("name", "")
                    entities_count[name] = entities_count.get(name, 0) + 1
                elif node.get("type") == "Tag":
                    name = node.get("name", "")
                    tags_count[name] = tags_count.get(name, 0) + 1
                    
        top_entities = [name for name, count in sorted(entities_count.items(), key=lambda x: x[1], reverse=True)[:10]]
        top_tags = [name for name, count in sorted(tags_count.items(), key=lambda x: x[1], reverse=True)[:5]]
        
        prompt = f"""You are an expert file archivist. You need to name a folder for a cluster of files.

Files in this cluster:
{doc_names}

Key Shared Entities:
{top_entities}

Shared Tags:
{top_tags}

Provide ONLY a short, descriptive folder name (maximum 3 words). Do not use quotes, special characters, or prefixes. Use Title Case.
Example: 'Financial Reports' or 'Human Resources'"""

        try:
            client = OpenAI(base_url=settings.llm.base_url, api_key=settings.llm.api_key or "lm-studio")
            response = client.chat.completions.create(
                model=settings.llm.clustering_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1
            )
            name = response.choices[0].message.content.strip()
            name = "".join([c for c in name if c.isalnum() or c.isspace() or c == '-' or c == '_'])
            return name if name else "Uncategorized"
        except Exception as e:
            logger.error("cluster_naming_failed", error=str(e))
            return "Uncategorized"
            
    def organize_files(self, confidence_threshold: float = 0.3) -> Dict[str, Dict[str, Any]]:
        """Runs clustering, names the clusters, and returns a mapping of doc_id -> {folder, confidence}."""
        clusters = self.find_clusters()
        mapping = {}
        
        for i, cluster in enumerate(clusters):
            folder_name = self.name_cluster(cluster)
            logger.info("cluster_named", name=folder_name, size=len(cluster))
            
            # Calculate per-document confidence based on how many shared entities
            # connect this document to others in the same cluster
            for doc_id in cluster:
                shared_count = 0
                total_neighbors = 0
                
                for neighbor in self.gm.graph.neighbors(doc_id):
                    node_type = self.gm.graph.nodes[neighbor].get("type")
                    if node_type in ("Entity", "Tag"):
                        total_neighbors += 1
                        # Check if this entity/tag is shared with other docs in the cluster
                        for other_doc in cluster:
                            if other_doc != doc_id and self.gm.graph.has_edge(other_doc, neighbor):
                                shared_count += 1
                                break
                
                confidence = shared_count / max(total_neighbors, 1)
                
                if confidence < confidence_threshold and len(cluster) > 1:
                    mapping[doc_id] = {"folder": "Unsorted", "confidence": confidence}
                else:
                    mapping[doc_id] = {"folder": folder_name, "confidence": confidence}
                
        return mapping
