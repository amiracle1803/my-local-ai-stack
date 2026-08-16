"""
AGI Brain v3 — Scaled Architecture with JEPA + LLM Fusion
================================================================
- 1024-dim internal representation (projected from 384-dim frozen encoder)
- 12-layer MLP backbone (seq_len=1 ⇒ attention is identity, so q/k/RoPE removed)
- JEPA: Joint Embedding Predictive Architecture with EMA target network
- Total: ~260M params, fits RTX 4070 8GB at bs=32
"""
import torch
import torch.nn as nn
import torch.nn.functional as F
import copy
from typing import Dict, List, Optional, Any
try:
    from sentence_transformers import SentenceTransformer
except Exception:
    SentenceTransformer = None  # fallback if package unavailable

# Config
INTERNAL_DIM = 1024
TEXT_ENC_DIM = 384
NUM_HEADS = 16
NUM_LAYERS = 12
FFN_DIM = INTERNAL_DIM * 4
DROPOUT = 0.1


# ============================================================
# BACKBONE COMPONENTS
# ============================================================

class RMSNorm(nn.Module):
    def __init__(self, dim, eps=1e-6):
        super().__init__()
        self.eps = eps
        self.weight = nn.Parameter(torch.ones(dim))
    def forward(self, x):
        rms = torch.rsqrt(x.pow(2).mean(-1, keepdim=True) + self.eps)
        return x * rms * self.weight


class TokenMixer(nn.Module):
    """Token-wise MLP. seq_len=1 ⇒ cross-token attention is the identity,
    so q/k/RoPE are removed; this is an honest per-token MLP path."""
    def __init__(self, dim, dropout=0.0):
        super().__init__()
        self.v_proj = nn.Linear(dim, dim, bias=False)
        self.o_proj = nn.Linear(dim, dim, bias=False)
        self.dropout = nn.Dropout(dropout)

    def forward(self, x, mask=None):
        return self.dropout(self.o_proj(F.gelu(self.v_proj(x))))


class TransformerBlock(nn.Module):
    def __init__(self, dim, num_heads, ffn_dim, dropout=0.1):
        super().__init__()
        self.attn_norm = RMSNorm(dim)
        self.attn = TokenMixer(dim, dropout=dropout)
        self.ffn_norm = RMSNorm(dim)
        self.ffn = nn.Sequential(
            nn.Linear(dim, ffn_dim, bias=False),
            nn.GELU(),
            nn.Linear(ffn_dim, dim, bias=False),
            nn.Dropout(dropout),
        )
        
    def forward(self, x, mask=None):
        x = x + self.attn(self.attn_norm(x), mask)
        x = x + self.ffn(self.ffn_norm(x))
        return x


class TransformerBackbone(nn.Module):
    def __init__(self, dim, num_heads, num_layers, ffn_dim, dropout=0.1):
        super().__init__()
        self.layers = nn.ModuleList([
            TransformerBlock(dim, num_heads, ffn_dim, dropout)
            for _ in range(num_layers)
        ])
        self.final_norm = RMSNorm(dim)
        
    def forward(self, x, mask=None):
        for layer in self.layers:
            x = layer(x, mask)
        return self.final_norm(x)


# ============================================================
# JEPA: JOINT EMBEDDING PREDICTIVE ARCHITECTURE
# ============================================================
class JEPAPredictor(nn.Module):
    """
    Predicts future latent representations.
    context → predictor → predicted_target
    target is from EMA of backbone (target encoder).
    """
    def __init__(self, dim, hidden_dim):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(dim, hidden_dim),
            nn.GELU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.GELU(),
            nn.Linear(hidden_dim, dim),
        )
    
    def forward(self, context):
        return self.net(context)


class JEPATargetEncoder(nn.Module):
    """EMA copy of backbone — produces target representations."""
    def __init__(self, backbone: TransformerBackbone):
        super().__init__()
        self.backbone = copy.deepcopy(backbone)
        for p in self.parameters():
            p.requires_grad = False
    
    @torch.no_grad()
    def forward(self, x, mask=None):
        return self.backbone(x, mask)
    
    @torch.no_grad()
    def update(self, context_backbone: TransformerBackbone, momentum=0.996):
        for tp, sp in zip(self.backbone.parameters(), context_backbone.parameters()):
            tp.data = momentum * tp.data + (1 - momentum) * sp.data


# ============================================================
# MEMORY MODULE
# ============================================================

# ============================================================
# REASONING HEADS
# ============================================================

class CausalReasoningHead(nn.Module):
    """Predict effects from causes in latent space."""
    def __init__(self, dim, hidden_dim):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(dim, hidden_dim), nn.GELU(),
            nn.Linear(hidden_dim, hidden_dim), nn.GELU(),
            nn.Linear(hidden_dim, dim),
        )
    def forward(self, cause_emb):
        return self.net(cause_emb)


# ============================================================
# AGI BRAIN V3
# ============================================================

class AGIBrainV3(nn.Module):
    """
    Scaled AGI architecture combining JEPA + LLM understanding.

    Pipeline:
    1. Frozen text encoder (all-MiniLM-L6-v2) → 384-dim
    2. Projection: 384 → 1024
    3. MLP backbone (12 layers) — seq_len=1, no attention
    4. JEPA: predict future representations (EMA target network)
    5. Reasoning head: causal
    6. Phase integration: fuse all streams
    """

    def __init__(self, device='cuda'):
        super().__init__()
        self.device = device
        self.internal_dim = INTERNAL_DIM
        self.text_enc_dim = TEXT_ENC_DIM

        # ---- Frozen text encoder ----
        self.text_encoder = TextEncoder(self.text_enc_dim, device)

        # ---- Projection 384 → 1024 ----
        self.text_proj = nn.Sequential(
            nn.Linear(self.text_enc_dim, INTERNAL_DIM, bias=False),
            RMSNorm(INTERNAL_DIM),
        )

        # ---- Transformer backbone ----
        self.backbone = TransformerBackbone(
            INTERNAL_DIM, NUM_HEADS, NUM_LAYERS, FFN_DIM, DROPOUT
        )

        # ---- JEPA ----
        self.jepa_target = JEPATargetEncoder(self.backbone)  # EMA copy
        self.jepa_predictor = JEPAPredictor(INTERNAL_DIM, INTERNAL_DIM * 2)

        # ---- Reasoning head ----
        self.causal_head = CausalReasoningHead(INTERNAL_DIM, INTERNAL_DIM * 2)

        # ---- Per-relation dedicated heads: decouple shared integrated into
        # task-specific projections so losses don't fight over one embedding.
        self.same_head = CausalReasoningHead(INTERNAL_DIM, INTERNAL_DIM * 2)      # SAME / comp
        self.diff_head = CausalReasoningHead(INTERNAL_DIM, INTERNAL_DIM * 2)      # DIFFERENT / NO_REL
        self.opp_head = CausalReasoningHead(INTERNAL_DIM, INTERNAL_DIM * 2)       # OPPOSITE
        self.ana_head = CausalReasoningHead(INTERNAL_DIM, INTERNAL_DIM * 2)       # ANALOGY

        # ---- Phase integration: lightweight gated residual ----
        # Replaces dead 8× concat + 80M-param MLP with a ~2M-param gate.
        self.phase_gate = nn.Sequential(
            nn.Linear(INTERNAL_DIM, INTERNAL_DIM),
            nn.Sigmoid(),
        )
        self.phase_residual = nn.Sequential(
            nn.Linear(INTERNAL_DIM, INTERNAL_DIM, bias=False),
            RMSNorm(INTERNAL_DIM),
        )

        self._init_weights()
        self.step_count = 0
    
    def _init_weights(self):
        for name, m in self.named_modules():
            if isinstance(m, nn.Linear):
                nn.init.normal_(m.weight, std=0.02)
                if hasattr(m, 'bias') and m.bias is not None:
                    nn.init.zeros_(m.bias)
    
    def count_params(self):
        trainable = sum(p.numel() for p in self.parameters() if p.requires_grad)
        frozen = sum(p.numel() for p in self.parameters() if not p.requires_grad)
        return {'trainable': trainable, 'frozen': frozen, 'total': trainable + frozen}
    
    def encode_text(self, texts: List[str]) -> torch.Tensor:
        """Encode text → projected internal representation."""
        raw = torch.tensor(self.text_encoder.encode_text(texts), dtype=torch.float32, device=self.device)
        text_feat = self.text_encoder(raw)['embedding']
        return self.text_proj(text_feat)  # (B, 1024)
    
    def update_jepa_target(self, momentum=0.996):
        """Update EMA target network."""
        self.jepa_target.update(self.backbone, momentum)
    
    def forward(self, texts: List[str]) -> Dict[str, torch.Tensor]:
        """Full forward pass."""
        self.step_count += 1
        B = len(texts)
        D = self.internal_dim

        # 1. Encode text → projected 1024-dim
        projected = self.encode_text(texts).unsqueeze(1)  # (B, 1, 1024)

        # 2. Backbone processing
        backbone_out = self.backbone(projected).squeeze(1)  # (B, 1024)

        # 3. JEPA prediction (for training)
        with torch.no_grad():
            target_out = self.jepa_target(projected).squeeze(1)  # (B, 1024)
        jepa_pred = self.jepa_predictor(backbone_out)  # (B, 1024)

        # 4. Reasoning
        causal_effect = self.causal_head(backbone_out)
        same_emb = self.same_head(backbone_out)
        diff_emb = self.diff_head(backbone_out)
        opp_emb = self.opp_head(backbone_out)
        ana_emb = self.ana_head(backbone_out)

        # 5. Phase integration: gated residual blend
        gate = self.phase_gate(backbone_out)
        integrated = gate * self.phase_residual(backbone_out) + (1 - gate) * backbone_out

        return {
            'integrated': integrated,
            'backbone_out': backbone_out,
            'jepa_pred': jepa_pred,
            'jepa_target': target_out,
            'causal_effect': causal_effect,
            'same': same_emb,
            'diff': diff_emb,
            'opp': opp_emb,
            'ana': ana_emb,
            'projected': projected.squeeze(1),
            'step': self.step_count,
        }

    def forward_projected(self, projected: torch.Tensor) -> Dict[str, torch.Tensor]:
        """
        Pure-GPU forward from pre-encoded projected embeddings.
        Skips all CPU text encoding — used for training.
        """
        B = projected.shape[0]
        D = self.internal_dim

        # Backbone
        x = projected.unsqueeze(1)  # (B, 1, D)
        backbone_out = self.backbone(x).squeeze(1)

        # JEPA
        with torch.no_grad():
            target_out = self.jepa_target(x).squeeze(1)
        jepa_pred = self.jepa_predictor(backbone_out)

        # Reasoning
        causal_effect = self.causal_head(backbone_out)
        same_emb = self.same_head(backbone_out)
        diff_emb = self.diff_head(backbone_out)
        opp_emb = self.opp_head(backbone_out)
        ana_emb = self.ana_head(backbone_out)

        # Phase integration: gated residual blend
        gate = self.phase_gate(backbone_out)
        integrated = gate * self.phase_residual(backbone_out) + (1 - gate) * backbone_out

        return {
            'integrated': integrated,
            'backbone_out': backbone_out,
            'jepa_pred': jepa_pred,
            'jepa_target': target_out,
            'causal_effect': causal_effect,
            'same': same_emb,
            'diff': diff_emb,
            'opp': opp_emb,
            'ana': ana_emb,
        }


# ============================================================
# FROZEN TEXT ENCODER
# ============================================================

class TextEncoder(nn.Module):
    """Frozen SBERT encoder with trainable projection head."""
    def __init__(self, dim, device='cpu'):
        super().__init__()
        self.dim = dim
        self.device = device
        self.model = None  # Lazy load
    
    def _ensure_model(self):
        if self.model is None:
            self.model = SentenceTransformer('all-MiniLM-L6-v2', device=self.device)
            for p in self.model.parameters():
                p.requires_grad = False
            print(f"  [TextEncoder] Loaded all-MiniLM-L6-v2 (384-dim, frozen)")
    
    def encode_text(self, texts: List[str]):
        if SentenceTransformer is None:
            # Dummy deterministic embedding: hash each string to a fixed seed vector
            import hashlib
            import numpy as np
            embeddings = []
            for txt in texts:
                h = hashlib.sha256(txt.encode('utf-8')).digest()
                rng = np.random.default_rng(int.from_bytes(h[:4], 'little'))
                embeddings.append(rng.standard_normal(384).astype('float32'))
            return np.stack(embeddings)
        else:
            self._ensure_model()
            return self.model.encode(texts, show_progress_bar=False, convert_to_numpy=True)
    
    def forward(self, embeddings: torch.Tensor):
        return {'embedding': embeddings, 'raw': embeddings}


# ============================================================
# MAIN: CREATE AND DISPLAY MODEL
# ============================================================

if __name__ == '__main__':
    brain = AGIBrainV3(device='cpu')
    counts = brain.count_params()
    print(f"\n{'='*60}")
    print(f"AGI Brain V3 — Scaled Architecture")
    print(f"{'='*60}")
    print(f"  Internal dim:       {INTERNAL_DIM}")
    print(f"  Backbone layers:    {NUM_LAYERS}")
    print(f"  FFN dim:            {FFN_DIM}")
    print(f"  Trainable params:   {counts['trainable']/1e6:.1f}M")
    print(f"  Frozen params:      {counts['frozen']/1e6:.1f}M")
    print(f"  Total params:       {counts['total']/1e6:.1f}M")
    
    # Test
    brain = AGIBrainV3(device='cpu')
    out = brain(texts=['The quick brown fox jumps over the lazy dog', 'She studied for the exam'])
    for k, v in out.items():
        if isinstance(v, torch.Tensor):
            print(f"  {k}: {v.shape}")
