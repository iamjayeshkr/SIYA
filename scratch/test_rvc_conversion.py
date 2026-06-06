import os
import sys
import time
from pathlib import Path
import numpy as np
from scipy.io.wavfile import write as wav_write

proj_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(proj_root / "EdgeRVC"))

from configs.config import Config as RVCConfig
from infer.modules.vc.modules import VC as RVC_VC

def main():
    # 1. Create a dummy input audio file (1s sine wave)
    sample_rate = 16000
    t = np.linspace(0, 1.0, sample_rate, endpoint=False)
    # 220Hz tone
    audio_data = 0.5 * np.sin(2 * np.pi * 220 * t)
    
    input_wav = proj_root / "scratch/dummy_input.wav"
    wav_write(str(input_wav), sample_rate, (audio_data * 32767).astype(np.int16))
    print(f"Created dummy input at: {input_wav}")
    
    # 2. Setup RVC environment variables
    os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
    os.environ["TORCH_MPS_HIGH_WATERMARK_RATIO"] = "0.0"
    os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
    
    os.environ["weight_root"] = str(proj_root)  # load from workspace root where shreya.pth is
    os.environ["index_root"] = str(proj_root)
    os.environ["outside_index_root"] = str(proj_root)
    os.environ["rmvpe_root"] = str(proj_root / "EdgeRVC/assets/rmvpe")
    
    # 3. Initialize config and VC
    # Save original directory
    orig_cwd = os.getcwd()
    os.chdir(str(proj_root / "EdgeRVC"))
    try:
        cfg = RVCConfig()
        cfg.device = "cpu"
        cfg.is_half = False
        
        vc = RVC_VC(cfg)
        print("Initialized RVC VC.")
        
        # Load Shreya model weights
        # sid is the filename in weight_root, which is shreya.pth
        vc.get_vc("shreya.pth")
        print("Loaded shreya.pth weights successfully.")
        
        # Run conversion
        print("Starting voice conversion...")
        start_time = time.time()
        info, output_path = vc.vc_single(
            sid=0,
            input_audio_path=str(input_wav),
            f0_up_key=0,
            f0_file=None,
            f0_method="pm",  # Use PM for faster CPU processing
            file_index="",
            file_index2=str(proj_root / "shreya.index"),
            index_rate=0.75,
            filter_radius=3,
            resample_sr=0,
            rms_mix_rate=0.25,
            protect=0.33,
            save_dir=str(proj_root / "scratch"),
            format1="wav",
        )
        elapsed = time.time() - start_time
        print(f"Voice conversion finished in {elapsed:.2f}s.")
        print(f"Info: {info}")
        print(f"Output path: {output_path}")
        
    finally:
        os.chdir(orig_cwd)

if __name__ == "__main__":
    main()
