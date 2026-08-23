import json
import structlog
from typing import Literal
from pydantic import BaseModel, Field
from openai import OpenAI
from pathlib import Path

from ..config import settings
from .store import GraphManager

logger = structlog.get_logger(__name__)

class QueryIntent(BaseModel):
    intent: Literal["FindDocuments", "SummarizeTopic", "EntityRelationships"] = Field(
        ..., description="The type of query the user is making."
    )
    entities: list[str] = Field(
        default_factory=list, description="Key entities extracted from the user's query."
    )
    topic: str | None = Field(
        default=None, description="The main topic or concept to summarize, if applicable."
    )

class IntentExtractor:
    def __init__(self, client: OpenAI):
        self.client = client
        self.model = settings.llm.graph_extraction_model
        
    def extract(self, query: str) -> QueryIntent:
        prompt = f"""
You are an expert GraphRAG query planner. Analyze the user's query and map it to one of three intents:
1. FindDocuments: The user is looking for a list of documents or files about a specific entity or concept.
2. SummarizeTopic: The user wants to learn about a topic, asking for an explanation, summary, or details.
3. EntityRelationships: The user wants to know what other entities/topics are related to a specific entity.

Extract the relevant entities from the query. Ensure the entities are proper nouns or core concepts (e.g., 'Kubernetes', 'cronjobs', 'Docker').

User Query: {query}
"""
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "query_intent",
                    "schema": QueryIntent.model_json_schema()
                }
            },
            temperature=0.0
        )
        content = response.choices[0].message.content
        return QueryIntent.model_validate_json(content)

class EvidenceAssembler:
    def __init__(self, graph_manager: GraphManager):
        self.graph_manager = graph_manager

    def assemble(self, intent: QueryIntent) -> str:
        if not intent.entities and not intent.topic:
            return "No specific entities or topics identified to search for."
            
        entity_match = [e.lower() for e in intent.entities]
        if intent.topic:
            entity_match.append(intent.topic.lower())
            
        graph = self.graph_manager.graph
        
        # 1. Find matched Entity/Tag/Document nodes in NetworkX graph
        matched_nodes = []
        for node, data in graph.nodes(data=True):
            node_type = data.get("type")
            name = data.get("name", "").lower()
            filename = data.get("filename", "").lower()
            
            if node_type in ("Entity", "Tag"):
                if any(m in name for m in entity_match):
                    matched_nodes.append((node, data.get("name", "")))
            elif node_type == "Document":
                if any(m in filename for m in entity_match):
                    matched_nodes.append((node, data.get("filename", "")))

        if not matched_nodes:
            return "No matching entities, tags, or filenames found in the knowledge graph."
            
        if intent.intent == "FindDocuments":
            doc_matches = {}
            for node, name in matched_nodes:
                node_type = graph.nodes[node].get("type")
                if node_type == "Document":
                    if node not in doc_matches:
                        doc_matches[node] = {"path": graph.nodes[node].get("path", ""), "entities": set()}
                    doc_matches[node]["entities"].add(f"Filename Match: {name}")
                else:
                    for neighbor in graph.neighbors(node):
                        if graph.nodes[neighbor].get("type") == "Document":
                            if neighbor not in doc_matches:
                                doc_matches[neighbor] = {"path": graph.nodes[neighbor].get("path", ""), "entities": set()}
                            doc_matches[neighbor]["entities"].add(name)
                        
            evidence = "Retrieved Documents:\n"
            for doc_id, data in list(doc_matches.items())[:10]:
                evidence += f"- Document: {Path(data['path']).name} matches {list(data['entities'])}\n"
            return evidence
            
        elif intent.intent == "EntityRelationships":
            co_occurrences = {}
            for node, name1 in matched_nodes:
                node_type = graph.nodes[node].get("type")
                if node_type == "Document": continue # Only relate entities/tags
                
                for doc in graph.neighbors(node):
                    if graph.nodes[doc].get("type") == "Document":
                        for other in graph.neighbors(doc):
                            if other != node and graph.nodes[other].get("type") in ("Entity", "Tag"):
                                name2 = graph.nodes[other].get("name", "")
                                pair = tuple(sorted([name1, name2]))
                                co_occurrences[pair] = co_occurrences.get(pair, 0) + 1
                                
            sorted_pairs = sorted(co_occurrences.items(), key=lambda x: x[1], reverse=True)[:15]
            evidence = "Related Entities/Tags:\n"
            for (source, target), count in sorted_pairs:
                evidence += f"- '{source}' co-occurs with '{target}' in {count} document(s).\n"
            return evidence
            
        elif intent.intent == "SummarizeTopic":
            doc_matches = {}
            for node, name in matched_nodes:
                node_type = graph.nodes[node].get("type")
                if node_type == "Document":
                    doc_matches[node] = graph.nodes[node]
                else:
                    for neighbor in graph.neighbors(node):
                        if graph.nodes[neighbor].get("type") == "Document":
                            doc_matches[neighbor] = graph.nodes[neighbor]
                        
            evidence = "Document Summaries for Context:\n\n"
            for doc_id, data in list(doc_matches.items())[:3]:
                filename = Path(data.get("path", "")).name
                summary = data.get("summary", "No summary available.")
                evidence += f"--- [Citation: {filename}] ---\n{summary}\n\n"
            return evidence
            
        return "No evidence could be gathered."

class SynthesisEngine:
    def __init__(self, client: OpenAI):
        self.client = client
        self.model = settings.llm.graph_extraction_model
        
    def synthesize(self, query: str, evidence: str) -> str:
        prompt = f"""
You are a precise knowledge assistant. You must answer the user's query using ONLY the provided evidence.

EVIDENCE:
{evidence}

USER QUERY:
{query}

RULES:
1. If the evidence does not contain the answer, state that you do not have enough information in the vault.
2. For ANY factual claim made based on the evidence, you MUST append an inline citation EXACTLY as provided in the evidence headers.
3. Example of a good citation: "Kubernetes uses CronJobs to manage time-based tasks [Citation: cronjobs.docx, Page 1]."
4. Be concise and direct.
"""
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2
        )
        return response.choices[0].message.content

