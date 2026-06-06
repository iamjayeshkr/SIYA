import asyncio
import sys
import logging
import time

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)

sys.path.insert(0, 'src')

from vani.audio.indic_tts_adapter import synthesize_and_play, _engine_ready

async def main():
    print("Waiting for Indic-TTS engine to initialize (downloading checkpoints if needed)...")
    start_time = time.time()
    
    # Wait until engine is ready
    while not _engine_ready.is_set():
        await asyncio.sleep(2)
        elapsed = time.time() - start_time
        print(f"Waiting... elapsed: {elapsed:.1f}s")
        
    print("Engine ready! Synthesizing and playing text...")
    success = await synthesize_and_play("Haan yaar, kaam ho gaya bilkul theek se.")
    print(f"Playout success: {success}")
    
    # Try another one to test cache hit / performance
    print("Synthesizing and playing second phrase...")
    success2 = await synthesize_and_play("Haan yaar")
    print(f"Playout success 2: {success2}")

if __name__ == "__main__":
    asyncio.run(main())
