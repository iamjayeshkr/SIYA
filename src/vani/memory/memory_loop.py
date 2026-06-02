"""
memory_loop.py — Fixed v2

Fixes:
  1. Sleep 1s → 10s — har second save karna band, ab 10 second mein ek baar
  2. Batch save — ek ek message save nahi hoga, saare naye messages ek hi call mein
  3. CancelledError properly propagate hota hai
"""

import asyncio
import time
import logging
from vani.memory.memory_store import ConversationMemory
from pydantic import BaseModel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)


class MemoryExtractor:
    def __init__(self):
        self.saved_message_count = 0

    def _serialize_for_hash(self, obj):
        if isinstance(obj, BaseModel):
            return obj.model_dump()
        elif isinstance(obj, dict):
            return {k: self._serialize_for_hash(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._serialize_for_hash(item) for item in obj]
        else:
            return obj

    async def run(self, session):
        """
        Infinite loop — must be run as asyncio.Task, cancelled on session end.
        Saves in batches every 10 seconds — not every 1 second.
        """
        memory = ConversationMemory("Rudra_Vani")

        try:
            while True:
                await asyncio.sleep(10)   # ← 1s se 10s — 10x kam saves

                current_chat_history = session

                if len(current_chat_history) <= self.saved_message_count:
                    continue   # kuch naya nahi — skip

                new_messages = current_chat_history[self.saved_message_count:]

                # Saare naye messages ek hi conversation_wrapper mein
                # Ek call — ek save — done
                serialized_messages = [
                    self._serialize_for_hash(msg) for msg in new_messages
                ]

                conversation_wrapper = {
                    "messages":  serialized_messages,
                    "timestamp": time.time()
                }

                success = memory.save_conversation(conversation_wrapper)

                if success:
                    logging.info(f"Saved {len(new_messages)} new messages in one batch")
                else:
                    logging.error("Batch save failed")

                self.saved_message_count = len(current_chat_history)

        except asyncio.CancelledError:
            logging.info("[memory] Extraction task cancelled — session ended.")
            raise
