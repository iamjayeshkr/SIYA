"""
src/vani/memory/knowledge_engine.py — SQLite-backed Knowledge Graph Engine
"""

from __future__ import annotations

import json
import sqlite3
import logging
import asyncio
from typing import List, Dict, Any, Optional
from vani.memory.vector_store import SQLiteVectorStore, cosine_similarity, DB_PATH

logger = logging.getLogger("vani.memory.knowledge_engine")


class KnowledgeEngine:
    """
    Manages entities, relationships, fact verification, and citation sourcing.
    Uses Vanni's centralized SQLite DB.
    """

    def __init__(self) -> None:
        self.db_path = DB_PATH
        self.vector_store = SQLiteVectorStore()
        self._init_db()

    def _init_db(self) -> None:
        """Initialize Knowledge Graph schema tables in SQLite."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            # 1. Entities table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS kg_entities (
                    id TEXT PRIMARY KEY,
                    name TEXT UNIQUE NOT NULL,
                    type TEXT,
                    description TEXT,
                    embedding TEXT
                );
                """
            )
            # 2. Relations table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS kg_relations (
                    id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    relation_type TEXT,
                    confidence REAL DEFAULT 1.0,
                    FOREIGN KEY(source_id) REFERENCES kg_entities(id),
                    FOREIGN KEY(target_id) REFERENCES kg_entities(id)
                );
                """
            )
            # 3. Citations table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS kg_citations (
                    id TEXT PRIMARY KEY,
                    source_url TEXT,
                    content_chunk TEXT,
                    confidence_score REAL DEFAULT 1.0
                );
                """
            )
            conn.commit()

    async def add_entity(self, name: str, type_str: str, description: str) -> str:
        ent_id = f"ent_{name.lower().replace(' ', '_')}"
        emb = await self.vector_store.get_embedding(f"{name} {description}")
        emb_json = json.dumps(emb)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO kg_entities (id, name, type, description, embedding)
                VALUES (?, ?, ?, ?, ?)
                """,
                (ent_id, name, type_str, description, emb_json)
            )
            conn.commit()
        return ent_id

    async def add_relation(
        self,
        source_name: str,
        target_name: str,
        relation_type: str,
        confidence: float = 1.0
    ) -> None:
        source_id = f"ent_{source_name.lower().replace(' ', '_')}"
        target_id = f"ent_{target_name.lower().replace(' ', '_')}"
        
        # Ensure entities exist in kg_entities so foreign keys don't fail
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO kg_entities (id, name) VALUES (?, ?)",
                (source_id, source_name)
            )
            conn.execute(
                "INSERT OR IGNORE INTO kg_entities (id, name) VALUES (?, ?)",
                (target_id, target_name)
            )
            
            rel_id = f"rel_{source_id}_{target_id}_{relation_type}"
            conn.execute(
                """
                INSERT OR REPLACE INTO kg_relations (id, source_id, target_id, relation_type, confidence)
                VALUES (?, ?, ?, ?, ?)
                """,
                (rel_id, source_id, target_id, relation_type, confidence)
            )
            conn.commit()

    async def add_citation(self, source_url: str, content_chunk: str, confidence_score: float = 1.0) -> None:
        import uuid
        cit_id = uuid.uuid4().hex[:16]
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO kg_citations (id, source_url, content_chunk, confidence_score)
                VALUES (?, ?, ?, ?)
                """,
                (cit_id, source_url, content_chunk, confidence_score)
            )
            conn.commit()

    async def get_relations(self, source_name: str) -> Dict[str, List[Dict[str, Any]]]:
        source_id = f"ent_{source_name.lower().replace(' ', '_')}"
        outgoing = []
        incoming = []
        
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            
            # Outgoing relations
            out_rows = conn.execute(
                """
                SELECT r.relation_type, r.confidence, e.name as target_name
                FROM kg_relations r
                JOIN kg_entities e ON r.target_id = e.id
                WHERE r.source_id = ?
                """,
                (source_id,)
            ).fetchall()
            
            for row in out_rows:
                outgoing.append({
                    "target_name": row["target_name"],
                    "relation_type": row["relation_type"],
                    "confidence": row["confidence"]
                })
                
            # Incoming relations
            in_rows = conn.execute(
                """
                SELECT r.relation_type, r.confidence, e.name as source_name
                FROM kg_relations r
                JOIN kg_entities e ON r.source_id = e.id
                WHERE r.target_id = ?
                """,
                (source_id,)
            ).fetchall()
            
            for row in in_rows:
                incoming.append({
                    "source_name": row["source_name"],
                    "relation_type": row["relation_type"],
                    "confidence": row["confidence"]
                })
                
        return {"outgoing": outgoing, "incoming": incoming}

    async def verify_fact(self, source_name: str, relation_type: str, target_name: str) -> Dict[str, Any]:
        source_id = f"ent_{source_name.lower().replace(' ', '_')}"
        target_id = f"ent_{target_name.lower().replace(' ', '_')}"
        
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT confidence FROM kg_relations
                WHERE source_id = ? AND target_id = ? AND relation_type = ?
                """,
                (source_id, target_id, relation_type)
            ).fetchone()
            
        if row:
            return {"verified": True, "confidence": row[0]}
        return {"verified": False, "confidence": 0.0}
