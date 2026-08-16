#!/bin/bash
# kohya-ss training entrypoint
# Usage: docker run ... --dataset /data --output /output --character akari --rank 8 --steps 800

set -e

# Parse arguments
DATASET=""
OUTPUT=""
CHARACTER=""
RANK=8
STEPS=800
MODEL="krea2"
PRECISION="bf16"
NETWORK_DIM=32
NETWORK_ALPHA=32
LEARNING_RATE=1e-4
LR_SCHEDULER="cosine_with_restarts"
LR_WARMUP=100
BATCH_SIZE=1
MAX_TOKEN_LENGTH=225
SAVE_EVERY_N_EPOCHS=1
MIXED_PRECISION="bf16"
GRADIENT_CHECKPOINTING="true"
SHUFFLE_CAPTION="true"
KEEP_TOKENS=1
NOISE_OFFSET=0.0
MIN_SNR_GAMMA=5.0

while [[ $# -gt 0 ]]; do
    case $1 in
        --dataset) DATASET="$2"; shift 2 ;;
        --output) OUTPUT="$2"; shift 2 ;;
        --character) CHARACTER="$2"; shift 2 ;;
        --rank) RANK="$2"; shift 2 ;;
        --steps) STEPS="$2"; shift 2 ;;
        --model) MODEL="$2"; shift 2 ;;
        --precision) PRECISION="$2"; shift 2 ;;
        --network-dim) NETWORK_DIM="$2"; shift 2 ;;
        --network-alpha) NETWORK_ALPHA="$2"; shift 2 ;;
        --learning-rate) LEARNING_RATE="$2"; shift 2 ;;
        --lr-scheduler) LR_SCHEDULER="$2"; shift 2 ;;
        --lr-warmup) LR_WARMUP="$2"; shift 2 ;;
        --batch-size) BATCH_SIZE="$2"; shift 2 ;;
        --max-token-length) MAX_TOKEN_LENGTH="$2"; shift 2 ;;
        --save-every-n-epochs) SAVE_EVERY_N_EPOCHS="$2"; shift 2 ;;
        --mixed-precision) MIXED_PRECISION="$2"; shift 2 ;;
        --gradient-checkpointing) GRADIENT_CHECKPOINTING="$2"; shift 2 ;;
        --shuffle-caption) SHUFFLE_CAPTION="$2"; shift 2 ;;
        --keep-tokens) KEEP_TOKENS="$2"; shift 2 ;;
        --noise-offset) NOISE_OFFSET="$2"; shift 2 ;;
        --min-snr-gamma) MIN_SNR_GAMMA="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

if [[ -z "$DATASET" ]]; then
    echo "Error: --dataset is required"
    exit 1
fi

if [[ -z "$OUTPUT" ]]; then
    echo "Error: --output is required"
    exit 1
fi

if [[ -z "$CHARACTER" ]]; then
    echo "Error: --character is required"
    exit 1
fi

echo "=== kohya-ss LoRA Training ==="
echo "Dataset: $DATASET"
echo "Output: $OUTPUT"
echo "Character: $CHARACTER"
echo "Rank: $RANK"
echo "Steps: $STEPS"
echo "Model: $MODEL"
echo "Precision: $PRECISION"
echo "Network Dim: $NETWORK_DIM"
echo "Network Alpha: $NETWORK_ALPHA"
echo "Learning Rate: $LEARNING_RATE"

# Create output directory
mkdir -p "$OUTPUT"

# Build the training command
cd /opt/sd-scripts

# For krea2/Qwen-Image, we need the appropriate training script
# krea2 model uses generic train_network.py (non-FLUX/SDXL architecture)
if [[ "$MODEL" == "krea2" ]] || [[ "$MODEL" == "qwen" ]]; then
    TRAIN_SCRIPT="train_network.py"
    MODEL_ARGS="--pretrained_model_name_or_path=/models/krea2_turbo_fp8_scaled.safetensors"
else
    TRAIN_SCRIPT="sdxl_train_network.py"
    MODEL_ARGS="--pretrained_model_name_or_path=/models/krea2_turbo_fp8_scaled.safetensors"
fi

# Prepare dataset metadata (captions)
# kohya expects a directory structure with images and .txt caption files
# or a metadata.jsonl file

TRAIN_CMD="python3.10 $TRAIN_SCRIPT \
    $MODEL_ARGS \
    --train_data_dir=$DATASET \
    --output_dir=$OUTPUT \
    --output_name=${CHARACTER}_lora \
    --save_model_as=safetensors \
    --network_module=networks.lora \
    --network_dim=$NETWORK_DIM \
    --network_alpha=$NETWORK_ALPHA \
    --network_train_unet_only \
    --learning_rate=$LEARNING_RATE \
    --lr_scheduler=$LR_SCHEDULER \
    --lr_warmup_steps=$LR_WARMUP \
    --max_train_steps=$STEPS \
    --train_batch_size=$BATCH_SIZE \
    --max_token_length=$MAX_TOKEN_LENGTH \
    --mixed_precision=$MIXED_PRECISION \
    --gradient_checkpointing \
    --shuffle_caption \
    --keep_tokens=$KEEP_TOKENS \
    --noise_offset=$NOISE_OFFSET \
    --min_snr_gamma=$MIN_SNR_GAMMA \
    --save_every_n_epochs=$SAVE_EVERY_N_EPOCHS \
    --logging_dir=$OUTPUT/logs \
    --log_with=tensorboard"

echo "Running: $TRAIN_CMD"
eval $TRAIN_CMD

# Find the output LoRA file
LORA_FILE=$(find "$OUTPUT" -name "${CHARACTER}_lora*.safetensors" | head -1)
if [[ -f "$LORA_FILE" ]]; then
    echo "=== Training Complete ==="
    echo "LoRA saved to: $LORA_FILE"
    # Copy to standard location
    cp "$LORA_FILE" "$OUTPUT/${CHARACTER}_lora.safetensors"
else
    echo "Warning: LoRA file not found in $OUTPUT"
    exit 1
fi
