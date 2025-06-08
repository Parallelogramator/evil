# streaming/asr.py

import logging
import numpy as np
import config
from optimum.intel import OVModelForSpeechSeq2Seq # Using OpenVINO optimized class
from transformers import AutoProcessor
import openvino as ov

# Configure logging (assuming basic setup elsewhere or use default)
# logging.basicConfig(level=logging.INFO) # Example basic config
logger = logging.getLogger(__name__) # Use __name__ for standard practice

# --- Global variables for model and processor ---
ov_model = None
processor = None
model_loaded = False
# ---

def init_asr_model():
    """
    Initializes and loads the Whisper ASR model using OpenVINO.
    Follows the pattern: Load Processor -> Load Model.
    """
    global ov_model, processor, model_loaded

    if model_loaded:
        logger.info("ASR model already loaded.")
        return True

    logger.info(f"Loading Whisper model '{config.WHISPER_MODEL_ID}' for OpenVINO on device '{config.OV_DEVICE}'...")
    logger.info(f"Model cache directory: {config.OV_CACHE_DIR}")

    try:
        # --- Optional: Informative OpenVINO device check ---
        try:
            core = ov.Core()
            available_devices = core.available_devices
            logger.info(f"OpenVINO available devices: {available_devices}")
            if config.OV_DEVICE not in available_devices and config.OV_DEVICE != "AUTO":
                 logger.warning(f"Specified OV_DEVICE '{config.OV_DEVICE}' not explicitly found in {available_devices}. OpenVINO might fall back or use AUTO behavior.")
            # NPU Note: Explicit NPU selection might change in future OpenVINO/Optimum versions.
            # 'AUTO' is generally preferred for portability.
        except Exception as e:
            logger.error(f"Error during OpenVINO Core check: {e}")
        # ---

        # Step 1 (Example): Load processor
        logger.info(f"Loading processor for {config.WHISPER_MODEL_ID}...")
        processor = AutoProcessor.from_pretrained(
            config.WHISPER_MODEL_ID,
            cache_dir=config.OV_CACHE_DIR
        )
        logger.info("Processor loaded.")

        # Step 1 (Example): Load model (OpenVINO specific loading/conversion)
        logger.info(f"Loading/Exporting model {config.WHISPER_MODEL_ID} for OpenVINO...")
        ov_model = OVModelForSpeechSeq2Seq.from_pretrained(
            config.WHISPER_MODEL_ID,
            export=True,          # Export to OpenVINO format if needed
            device=config.OV_DEVICE,     # Target device (CPU, GPU, AUTO)
            cache_dir=config.OV_CACHE_DIR, # Cache for downloaded model AND exported model
            ov_config={"CACHE_DIR": config.OV_CACHE_DIR}, # Cache for compiled model blobs
            trust_remote_code=True # Allow custom code if present in model repo
        )
        # Note: Setting forced_decoder_ids like in the example usually isn't
        # needed here as language/task are specified during generation.
        # If needed: ov_model.config.forced_decoder_ids = processor.get_decoder_prompt_ids(language=config.ASR_LANGUAGE, task="transcribe")
        logger.info("OpenVINO model loaded/exported.")

        # Optional Step: Compile model (can improve first inference latency)
        # logger.info("Compiling OpenVINO model (this may take a moment)...")
        # ov_model.compile() # This happens implicitly on first generate() if not called explicitly
        # logger.info("OpenVINO model compiled.")

        logger.info("OpenVINO Whisper model and processor initialized successfully.")
        model_loaded = True
        return True

    except ImportError as e:
         logger.error(f"ImportError loading model: {e}. Ensure required packages are installed (e.g., optimum[openvino], transformers, etc.)")
         model_loaded = False
    except Exception as e:
        logger.error(f"Failed to load OpenVINO Whisper model: {e}", exc_info=True)
        logger.error("Check model ID, network connection, cache directory permissions, and OpenVINO installation.")
        model_loaded = False

    return False


def transcribe_audio(audio_data: np.ndarray) -> str:
    """
    Performs speech recognition on the provided audio data using the loaded OpenVINO model.
    Follows the pattern: Preprocess Data -> Generate Tokens -> Decode Tokens.

    Args:
        audio_data: A numpy array containing the audio waveform (mono).

    Returns:
        The recognized text string, or an empty string if an error occurs or the model isn't loaded.
    """
    global ov_model, processor # Use the globally loaded model/processor

    if not model_loaded or ov_model is None or processor is None:
        logger.error("ASR model not initialized. Call init_asr_model() first.")
        return ""

    if not isinstance(audio_data, np.ndarray) or audio_data.size == 0:
        logger.warning("Received invalid or empty audio data for transcription.")
        return ""

    try:
        # Step 2 (Example): Preprocess Data (Extract features)
        # Ensure audio is float32, which Whisper models expect
        if audio_data.dtype != np.float32:
             audio_data = audio_data.astype(np.float32)
             # Optional: Normalize if needed (processor usually handles this)
             # if np.max(np.abs(audio_data)) > 1.0:
             #     audio_data /= np.max(np.abs(audio_data))

        inputs = processor(
            audio=audio_data,
            sampling_rate=config.SAMPLE_RATE, # Use configured sample rate
            return_tensors="pt"               # Return PyTorch tensors
        )
        input_features = inputs.input_features # Get the features needed by the model

        # Step 3 (Example): Generate Token IDs (Inference)
        # Prepare generation arguments
        generate_kwargs = {
            "language": config.ASR_LANGUAGE, # Specify target language
            "task": "transcribe",            # Specify task
            # Add other generation config from your config file if needed
            # e.g., "max_new_tokens": 128,
        }

        # VAD Note: Internal VAD options like in faster-whisper might not be directly
        # available or work the same way in Optimum/OpenVINO's generate method.
        # External VAD before calling transcribe_audio is often more reliable.
        # if config.USE_VAD_FILTER:
        #    logger.warning("Internal VAD filter in generate() might not be supported by Optimum/OV.")
            # generate_kwargs["vad_filter"] = True # Check Optimum documentation for support

        predicted_ids = ov_model.generate(input_features, **generate_kwargs)

        # Step 4 (Example): Decode Token IDs to Text
        # Use batch_decode even for single items, select the first result [0]
        transcription = processor.batch_decode(predicted_ids, skip_special_tokens=True)[0]

        # Clean up potential leading/trailing whitespace
        return transcription.strip()

    except Exception as e:
        logger.error(f"Error during OpenVINO Whisper transcription: {e}", exc_info=True)
        return ""

# Example Usage (optional, for testing the module directly)
# if __name__ == '__main__':
#     # Configure logging for standalone run
#     logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
#
#     # Make sure config.py has defaults set
#     class MockConfig:
#         WHISPER_MODEL_ID = "openai/whisper-tiny" # Use a small model for quick testing
#         OV_DEVICE = "CPU" # Or "AUTO", "GPU"
#         OV_CACHE_DIR = "./model_cache" # Ensure this directory exists or can be created
#         SAMPLE_RATE = 16000
#         ASR_LANGUAGE = "english" # Or the language you expect
#         USE_VAD_FILTER = False # Keep VAD related stuff off unless specifically tested
#
#     config = MockConfig()
#
#     # Create dummy audio (e.g., 5 seconds of silence or sine wave)
#     sr = config.SAMPLE_RATE
#     duration = 5
#     dummy_audio = np.sin(2 * np.pi * 440.0 * np.arange(sr * duration) / sr).astype(np.float32)
#     # Or load a real audio file:
#     # from datasets import load_dataset
#     # ds = load_dataset("hf-internal-testing/librispeech_asr_dummy", "clean", split="validation")
#     # sample = ds[0]["audio"]
#     # dummy_audio = sample["array"]
#     # config.SAMPLE_RATE = sample["sampling_rate"] # Important: Use actual sample rate
#
#     logger.info("Initializing ASR model...")
#     if init_asr_model():
#         logger.info("Model initialized. Transcribing dummy audio...")
#         result = transcribe_audio(dummy_audio)
#         logger.info(f"Transcription result: '{result}'")
#     else:
#         logger.error("Failed to initialize ASR model.")