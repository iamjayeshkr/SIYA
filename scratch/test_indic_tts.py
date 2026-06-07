import asyncio
import sys
import logging
import time

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)

sys.path.insert(0, 'src')

from vani.audio.indic_tts_adapter import synthesize_and_play, synthesize_and_play_chunked, _engine_ready

async def main():
    print("Waiting for Indic-TTS engine to initialize (downloading checkpoints if needed)...")
    start_time = time.time()
    
    # Wait until engine is ready
    while not _engine_ready.is_set():
        await asyncio.sleep(2)
        elapsed = time.time() - start_time
        print(f"Waiting... elapsed: {elapsed:.1f}s")
        
    print("Engine ready! Testing synthesize_and_play for short phrase...")
    success = await synthesize_and_play("Haan yaar, kaam ho gaya bilkul theek se.")
    print(f"Playout success: {success}")
    
    # Try another one to test cache hit / performance
    print("Synthesizing and playing second phrase (should be cache hit)...")
    success2 = await synthesize_and_play("Haan yaar")
    print(f"Playout success 2: {success2}")

    # Test chunked playback on a long paragraph
    long_text = "Samajh gaya. Main abhi aapka kaam kar raha hun. Ek second wait karo. Bilkul sahi se karunga aur phir aapko batata hun."
    print("Testing synthesize_and_play_chunked on a long multi-sentence paragraph...")
    start_chunked = time.time()
    success3 = await synthesize_and_play_chunked(long_text)
    duration = time.time() - start_chunked
    print(f"Chunked playout finished in {duration:.1f}s. Success: {success3}")

if __name__ == "__main__":
    asyncio.run(main())
