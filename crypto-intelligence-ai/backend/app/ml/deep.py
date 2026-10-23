"""Sequence models (LSTM / GRU / Transformer encoder) behind the same fit / predict_proba interface.

Requires PyTorch (`pip install -r requirements-dl.txt`) and ENABLE_DEEP_MODELS=true.
Standardisation statistics come from the training window only; early stopping uses the last 15% of the
training window (chronological split, no shuffling across the split).
"""
from __future__ import annotations

import numpy as np


class SequenceClassifier:
    def __init__(self, kind: str = "lstm", seq_len: int = 32, hidden: int = 48, layers: int = 1,
                 epochs: int = 30, patience: int = 5, lr: float = 1e-3, batch: int = 128,
                 dropout: float = 0.2, seed: int = 42):
        self.kind, self.seq_len, self.hidden, self.layers = kind, seq_len, hidden, layers
        self.epochs, self.patience, self.lr, self.batch, self.dropout, self.seed = epochs, patience, lr, batch, dropout, seed
        self.context_rows = seq_len - 1
        self.classes_ = np.array([0, 1, 2])

    def _net(self, n_features: int):
        import torch
        from torch import nn

        kind, hidden, layers, dropout = self.kind, self.hidden, self.layers, self.dropout

        class Net(nn.Module):
            def __init__(self):
                super().__init__()
                if kind == "transformer":
                    self.inp = nn.Linear(n_features, hidden)
                    enc = nn.TransformerEncoderLayer(hidden, nhead=4, dim_feedforward=hidden * 2,
                                                     dropout=dropout, batch_first=True)
                    self.body = nn.TransformerEncoder(enc, num_layers=2)
                    self.pos = nn.Parameter(torch.zeros(1, 512, hidden))
                else:
                    rnn = nn.LSTM if kind == "lstm" else nn.GRU
                    self.body = rnn(n_features, hidden, num_layers=layers, batch_first=True)
                self.drop = nn.Dropout(dropout)
                self.head = nn.Linear(hidden, 3)

            def forward(self, x):
                if kind == "transformer":
                    h = self.body(self.inp(x) + self.pos[:, :x.shape[1]])
                else:
                    h, _ = self.body(x)
                return self.head(self.drop(h[:, -1]))

        return Net()

    def _windows(self, Z: np.ndarray) -> np.ndarray:
        L = self.seq_len
        pad = np.repeat(Z[:1], L - 1, axis=0)        # only used when no earlier context exists
        full = np.concatenate([pad, Z], axis=0)
        return np.lib.stride_tricks.sliding_window_view(full, L, axis=0).transpose(0, 2, 1)

    def fit(self, X: np.ndarray, y: np.ndarray):
        import torch
        from torch import nn

        torch.manual_seed(self.seed)
        self.mu_ = X.mean(axis=0)
        self.sd_ = X.std(axis=0) + 1e-8
        W = self._windows(np.clip((X - self.mu_) / self.sd_, -8, 8)).astype(np.float32)
        yy = y.astype(np.int64)
        cut = int(len(W) * 0.85)
        Xt, yt = torch.from_numpy(W[:cut].copy()), torch.from_numpy(yy[:cut])
        Xv, yv = torch.from_numpy(W[cut:].copy()), torch.from_numpy(yy[cut:])
        self.net_ = self._net(X.shape[1])
        opt = torch.optim.AdamW(self.net_.parameters(), lr=self.lr, weight_decay=1e-3)
        loss_fn = nn.CrossEntropyLoss()
        best, best_state, bad = float("inf"), None, 0
        gen = torch.Generator().manual_seed(self.seed)
        for _ in range(self.epochs):
            self.net_.train()
            perm = torch.randperm(len(Xt), generator=gen)   # shuffles minibatches inside the training part only
            for i in range(0, len(Xt), self.batch):
                idx = perm[i:i + self.batch]
                opt.zero_grad()
                loss_fn(self.net_(Xt[idx]), yt[idx]).backward()
                nn.utils.clip_grad_norm_(self.net_.parameters(), 1.0)
                opt.step()
            self.net_.eval()
            with torch.no_grad():
                val = float(loss_fn(self.net_(Xv), yv)) if len(Xv) else 0.0
            if val < best - 1e-4:
                best, bad = val, 0
                best_state = {k: v.clone() for k, v in self.net_.state_dict().items()}
            else:
                bad += 1
                if bad >= self.patience:
                    break
        if best_state is not None:
            self.net_.load_state_dict(best_state)
        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        import torch

        W = self._windows(np.clip((X - self.mu_) / self.sd_, -8, 8)).astype(np.float32)
        self.net_.eval()
        out = []
        with torch.no_grad():
            for i in range(0, len(W), 2048):
                out.append(torch.softmax(self.net_(torch.from_numpy(W[i:i + 2048].copy())), dim=1).numpy())
        return np.concatenate(out, axis=0)
