import os
import shutil
import torch
import torch.nn as nn
import trainer.io
from trainer import Trainer, TrainerArgs
from trainer.logging import DummyLogger
from TTS.tts.layers.xtts.trainer.gpt_trainer import GPTTrainer, GPTTrainerConfig, GPTArgs
from TTS.tts.layers.xtts.gpt import GPT
from TTS.tts.layers.xtts.hifigan_decoder import HifiDecoder
from TTS.tts.models.xtts import Xtts
from TTS.tts.configs.shared_configs import BaseDatasetConfig
from TTS.tts.datasets import load_tts_samples
from datetime import datetime

# Allow cuDNN to find the best algorithm for our custom truncated tensor shapes
torch.backends.cudnn.benchmark = True
# torch.backends.cudnn.deterministic = True # This causes "unable to find engine" on RTX 3050 with weird conv1d shapes

# 1. Absolute Paths
BASE_DIR = r"D:\Hivericks\conversion-system\python-system"
DATASET_DIR = r"D:\Hivericks\conversion-system\train"
CHECKPOINT_DIR = r"C:\Users\rsvij\AppData\Local\tts\tts_models--multilingual--multi-dataset--xtts_v2"
OUTPUT_DIR = os.path.join(BASE_DIR, "output_finetune")

if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR, exist_ok=True)

# MONKEYPATCH 1: Windows File Management
def patched_setup_experiment(self, config, output_path):
    run_name = f"finetune_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    self.experiment_path = os.path.join(output_path, run_name)
    os.makedirs(self.experiment_path, exist_ok=True)
    self.output_path = self.experiment_path
    print(f"Patched setup_experiment: using {self.experiment_path}")

Trainer.setup_experiment = patched_setup_experiment
Trainer.save_training_script = lambda self: print("Skipping save_training_script.")
Trainer._setup_logger_config = lambda self, log_file: print(f"Skipping logger config for {log_file}")
trainer.io.copy_model_files = lambda *args, **kwargs: print("Skipping copy_model_files.")

# MONKEYPATCH 2: Force Gradient Checkpointing and correct Vocab/Max Tokens in Xtts
def patched_init_models(self):
    if self.tokenizer.tokenizer is not None:
        self.args.gpt_number_text_tokens = self.tokenizer.get_number_tokens()
        self.args.gpt_start_text_token = self.tokenizer.tokenizer.token_to_id("[START]")
        self.args.gpt_stop_text_token = self.tokenizer.tokenizer.token_to_id("[STOP]")

    if self.args.gpt_number_text_tokens:
        chkpt = getattr(self.args, 'gpt_checkpointing', False)
        print(f"Monkeypatched Xtts.init_models: GPT Checkpointing = {chkpt}, Text Tokens = {self.args.gpt_number_text_tokens}")
        print(f"Max Audio Tokens = {self.args.gpt_max_audio_tokens}, Max Text Tokens = {self.args.gpt_max_text_tokens}")
        self.gpt = GPT(
            layers=self.args.gpt_layers,
            model_dim=self.args.gpt_n_model_channels,
            start_text_token=self.args.gpt_start_text_token,
            stop_text_token=self.args.gpt_stop_text_token,
            heads=self.args.gpt_n_heads,
            max_text_tokens=self.args.gpt_max_text_tokens,
            max_mel_tokens=self.args.gpt_max_audio_tokens,
            max_prompt_tokens=self.args.gpt_max_prompt_tokens,
            number_text_tokens=self.args.gpt_number_text_tokens,
            num_audio_tokens=self.args.gpt_num_audio_tokens,
            start_audio_token=self.args.gpt_start_audio_token,
            stop_audio_token=self.args.gpt_stop_audio_token,
            use_perceiver_resampler=self.args.gpt_use_perceiver_resampler,
            code_stride_len=self.args.gpt_code_stride_len,
            checkpointing=chkpt,
        )

    self.hifigan_decoder = HifiDecoder(
        input_sample_rate=self.args.input_sample_rate,
        output_sample_rate=self.args.output_sample_rate,
        output_hop_length=self.args.output_hop_length,
        ar_mel_length_compression=self.args.gpt_code_stride_len,
        decoder_input_dim=self.args.decoder_input_dim,
        d_vector_dim=self.args.d_vector_dim,
        cond_d_vector_in_each_upsampling_layer=self.args.cond_d_vector_in_each_upsampling_layer,
    )

Xtts.init_models = patched_init_models

# MONKEYPATCH 3: Save VRAM by deleting unused parts
original_gpt_trainer_init = GPTTrainer.__init__
def patched_gpt_trainer_init(self, config):
    original_gpt_trainer_init(self, config)
    if hasattr(self.xtts, "hifigan_decoder") and self.xtts.hifigan_decoder is not None:
        print("VRAM OPT: Deleting hifigan_decoder")
        del self.xtts.hifigan_decoder
        self.xtts.hifigan_decoder = None
    
    if hasattr(self.xtts.gpt, "conditioning_perceiver"):
        print("VRAM OPT: Deleting conditioning_perceiver")
        del self.xtts.gpt.conditioning_perceiver
        self.xtts.gpt.conditioning_perceiver = None
    
    torch.cuda.empty_cache()

GPTTrainer.__init__ = patched_gpt_trainer_init

# MONKEYPATCH 4: Forcibly truncate batch tensors to avoid CUDA out-of-bounds on position embeddings
original_format_batch_on_device = GPTTrainer.format_batch_on_device
def patched_format_batch_on_device(self, batch):
    batch = original_format_batch_on_device(self, batch)
    max_t = self.config.model_args.gpt_max_text_tokens - 10
    max_a = self.config.model_args.gpt_max_audio_tokens - 10
    
    if batch['text_inputs'].shape[1] > max_t:
        batch['text_inputs'] = batch['text_inputs'][:, :max_t]
        batch['text_lengths'] = torch.clamp(batch['text_lengths'], max=max_t)
        
    if batch['audio_codes'].shape[1] > max_a:
        batch['audio_codes'] = batch['audio_codes'][:, :max_a]
        batch['wav_lengths'] = torch.clamp(batch['wav_lengths'], max=max_a * self.config.model_args.gpt_code_stride_len)
        
    return batch

GPTTrainer.format_batch_on_device = patched_format_batch_on_device

# 2. Dataset Configuration
dataset_config = BaseDatasetConfig(
    formatter="coqui",
    dataset_name="indian_english",
    path=DATASET_DIR,
    meta_file_train="metadata.csv",
    language="en",
)

# 3. GPT Trainer Configuration
config = GPTTrainerConfig(
    output_path=OUTPUT_DIR,
    run_name="finetune_indian_english",
    epochs=10,
    batch_size=1,
    eval_batch_size=1,
    run_eval=False,
    mixed_precision=False, # FP32 is more stable on 6GB laptop GPUs
    num_loader_workers=0,
    num_eval_loader_workers=0,
    lr=5e-6,
    optimizer_params={},
)
config.max_text_len = 300 # Character limit to avoid exceeding 402 BPE tokens
config.max_audio_len = 250000 # Sample limit (~11 seconds)

# 4. Model Arguments (GPTArgs) 
model_args = GPTArgs(
    max_conditioning_length=22050, 
    min_conditioning_length=22050, 
    gpt_loss_text_ce_weight=0.01,
    gpt_loss_mel_ce_weight=1.0,
    gpt_num_audio_tokens=1026,
    tokenizer_file=os.path.join(CHECKPOINT_DIR, "vocab.json"),
    mel_norm_file=os.path.join(CHECKPOINT_DIR, "mel_norms.pth"),
    dvae_checkpoint=os.path.join(CHECKPOINT_DIR, "dvae.pth"),
    xtts_checkpoint=os.path.join(CHECKPOINT_DIR, "model.pth"),
    output_sample_rate=24000,
)
model_args.gpt_checkpointing = True 
model_args.max_wav_length = 44100 
model_args.gpt_use_perceiver_resampler = False # Match our VRAM deletion
# Match XTTS-v2 checkpoint exactly to avoid shape mismatch
model_args.gpt_max_audio_tokens = 605
model_args.gpt_max_text_tokens = 402

config.model_args = model_args

# 5. Audio Configuration
config.audio.sample_rate = 22050
config.audio.output_sample_rate = 24000
config.audio.dvae_sample_rate = 22050
config.datasets = [dataset_config]

# 6. Load Samples
train_samples, eval_samples = load_tts_samples(dataset_config, eval_split=True, eval_split_size=0.01)

# 7. Initialize Trainer
trainer = Trainer(
    TrainerArgs(
        gpu=0,
        restore_path=None,
        grad_accum_steps=64,
    ),
    config,
    output_path=OUTPUT_DIR,
    model=GPTTrainer(config),
    train_samples=train_samples,
    eval_samples=eval_samples,
    dashboard_logger=DummyLogger(),
)

# 8. Start Fine-tuning
if __name__ == "__main__":
    print(f"Starting FINAL Fine-tuning loop (6GB STABLE)...")
    try:
        trainer.fit()
    except Exception as e:
        import traceback
        with open("error_log.txt", "w", encoding="utf-8") as f:
            f.write(traceback.format_exc())
        print(f"Training failed. Traceback written to error_log.txt")
