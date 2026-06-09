import time
import sys

print("=== 1. Starting Latency / Import Timing Test ===")
start_time = time.time()
try:
    import vani.reasoning as vani_reasoning
    duration = time.time() - start_time
    print(f"✅ Success! Imported vani_reasoning in {duration:.4f} seconds.")
    if duration < 0.2:
        print("🎉 Exceeded targets! Import is extremely fast (< 0.2s).")
    else:
        print("⚠️ Import took longer than expected.")
except Exception as e:
    print(f"❌ Failed to import vani.reasoning as vani_reasoning: {e}")
    sys.exit(1)

print("\n=== 2. Prompt Loading Test ===")
try:
    import vani.prompts as vani_prompts
    prompt = vani_prompts.get_final_prompt("full")
    print(f"Prompt length: {len(prompt)} characters.")
    
    # Check if a critical keyword exists
    if "Tu Siya hai" in prompt:
        print("✅ Success! Siya core Hinglish instructions loaded correctly from core_mode.txt.")
    else:
        print("❌ Error: 'Tu Siya hai' persona string not found in the compiled prompt!")
        sys.exit(1)
        
    if "CALL GO-TO RULES" in prompt:
        print("✅ Success! Call guidelines loaded correctly from call_mode.txt.")
        
    if "LIVE INTERRUPT" in prompt:
        print("✅ Success! Interruption guidelines loaded correctly from live_mode.txt.")
        
    if "TOOL CALLING RULES" in prompt:
        print("✅ Success! Tool rules loaded correctly from tool_mode.txt.")
        
    print("\nSample prompt prefix:")
    print("-" * 40)
    print("\n".join(prompt.split("\n")[:15]))
    print("-" * 40)
except Exception as e:
    print(f"❌ Failed to compile vani_prompts: {e}")
    sys.exit(1)

print("\n=== Verification Successful! ===")
