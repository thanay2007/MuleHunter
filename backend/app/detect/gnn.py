"""GraphSAGE over the incident subgraph.

**The argument this model exists to make.** A rule engine looking at one account
sees a grey account: some dormancy, a large credit, a quick forward. Thousands
of ordinary accounts look like that on any given Tuesday. Looking at the same
account's *neighbourhood* you see eight accounts on one handset, opened in the
same fortnight, all dormant for nine months, all forwarding within minutes,
all paying into the same four exchange deposits. That is not a grey account,
it is an organisation -- and none of that signal is a property of the account,
so no per-account model can reach it.

Two message-passing layers with edge features (time delta, amount, channel)
folded into the messages, a binary head for `is_mule`, and an auxiliary head
predicting `layer_index`. The auxiliary head is not decoration: forcing the
encoder to know *where* in a chain an account sits produces representations
that separate collectors from leaves, and the interdiction solver cares about
that difference far more than it cares about a marginal AUC point.

**Torch is optional.** Everything here imports defensively. If torch or PyG is
absent the module reports itself unavailable and the pipeline runs on LightGBM
alone -- that is the documented fallback, not a failure.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.config import settings
from app.graphstore.features import FEATURE_NAMES

log = logging.getLogger(__name__)

try:  # pragma: no cover - environment dependent
    import torch
    from torch import Tensor, nn

    TORCH_AVAILABLE = True
except ImportError:  # pragma: no cover
    TORCH_AVAILABLE = False
    Tensor = object  # type: ignore[assignment,misc]

try:  # pragma: no cover - environment dependent
    from torch_geometric.nn import SAGEConv

    PYG_AVAILABLE = TORCH_AVAILABLE
except ImportError:  # pragma: no cover
    PYG_AVAILABLE = False


#: Channel vocabulary, fixed so a saved model keeps its meaning.
CHANNELS: tuple[str, ...] = ("UPI", "IMPS", "NEFT", "CARD", "ATM_WITHDRAWAL")
EDGE_FEATURE_DIM: int = 3 + len(CHANNELS)  # log amount, log delay, night flag, channel


def is_available() -> bool:
    return PYG_AVAILABLE


@dataclass(frozen=True)
class GraphSample:
    """One incident, encoded for the network."""

    x: np.ndarray  # (n_nodes, N_FEATURES)
    edge_index: np.ndarray  # (2, n_edges)
    edge_attr: np.ndarray  # (n_edges, EDGE_FEATURE_DIM)
    y: np.ndarray  # (n_nodes,) is_mule
    layer: np.ndarray  # (n_nodes,) layer index, -1 where unknown
    account_ids: tuple[str, ...]


def encode_edges(
    amounts: np.ndarray,
    delays_seconds: np.ndarray,
    channels: list[str],
    night: np.ndarray,
) -> np.ndarray:
    """Edge features: value, how fast it followed the previous credit, channel.

    Delay is the informative one. The same ₹40,000 transfer means something
    quite different four seconds after a credit than four days after it, and a
    model that only sees node aggregates cannot represent that at all.
    """
    n = len(channels)
    out = np.zeros((n, EDGE_FEATURE_DIM), dtype=np.float32)
    out[:, 0] = np.log1p(np.maximum(amounts, 0.0))
    out[:, 1] = np.log1p(np.maximum(delays_seconds, 0.0))
    out[:, 2] = night.astype(np.float32)
    for i, channel in enumerate(channels):
        if channel in CHANNELS:
            out[i, 3 + CHANNELS.index(channel)] = 1.0
    return out


if TORCH_AVAILABLE and PYG_AVAILABLE:  # pragma: no branch

    class EdgeAwareSAGE(nn.Module):
        """GraphSAGE with edge features folded into each message.

        `SAGEConv` has no edge-feature slot, so edges are projected to a gate
        that scales the source representation before aggregation. Cheap, and it
        keeps the temporal signal in the message rather than bolting it on as a
        node feature afterwards, which would lose the per-edge resolution
        entirely.
        """

        def __init__(
            self,
            in_dim: int = len(FEATURE_NAMES),
            hidden: int | None = None,
            layers: int | None = None,
            dropout: float | None = None,
        ) -> None:
            super().__init__()
            hidden = hidden or settings.gnn_hidden_dim
            layers = layers or settings.gnn_layers
            dropout = settings.gnn_dropout if dropout is None else dropout

            self.input_norm = nn.BatchNorm1d(in_dim)
            self.edge_gate = nn.Sequential(
                nn.Linear(EDGE_FEATURE_DIM, hidden),
                nn.ReLU(),
                nn.Linear(hidden, hidden),
                nn.Sigmoid(),
            )
            self.project = nn.Linear(in_dim, hidden)
            self.convs = nn.ModuleList(
                [SAGEConv(hidden, hidden) for _ in range(layers)]
            )
            self.norms = nn.ModuleList(
                [nn.LayerNorm(hidden) for _ in range(layers)]
            )
            self.dropout = nn.Dropout(dropout)
            self.mule_head = nn.Linear(hidden, 1)
            # Auxiliary head over layer 0..7 plus an "unknown" bucket.
            self.layer_head = nn.Linear(hidden, 9)

        def forward(
            self, x: Tensor, edge_index: Tensor, edge_attr: Tensor
        ) -> tuple[Tensor, Tensor]:
            h = self.project(self.input_norm(x))

            for conv, norm in zip(self.convs, self.norms):
                gate = self.edge_gate(edge_attr)
                messages = h.clone()
                if edge_index.numel() > 0:
                    source = edge_index[0]
                    # Scale each source representation by its edge gate before
                    # the neighbourhood aggregation reads it.
                    scaled = torch.zeros_like(h)
                    scaled.index_add_(0, source, h[source] * gate)
                    counts = torch.zeros(h.size(0), 1, device=h.device)
                    counts.index_add_(
                        0, source, torch.ones(source.size(0), 1, device=h.device)
                    )
                    messages = torch.where(counts > 0, scaled / counts.clamp(min=1), h)

                h = conv(messages, edge_index)
                h = self.dropout(torch.relu(norm(h)))

            return self.mule_head(h).squeeze(-1), self.layer_head(h)

else:  # pragma: no cover - torch absent

    class EdgeAwareSAGE:  # type: ignore[no-redef]
        def __init__(self, *args: object, **kwargs: object) -> None:
            raise RuntimeError(
                "PyTorch Geometric is not installed. The pipeline runs on "
                "LightGBM alone; install torch and torch-geometric for the GNN."
            )


def train_gnn(
    samples: list[GraphSample], epochs: int | None = None
) -> tuple[object, dict[str, float]]:
    """Train the GNN on encoded incidents. Returns (model, metrics)."""
    if not is_available():
        raise RuntimeError("PyTorch Geometric is not installed")

    torch.manual_seed(settings.master_seed)
    epochs = epochs or settings.gnn_epochs

    model = EdgeAwareSAGE()
    optimiser = torch.optim.AdamW(model.parameters(), lr=settings.gnn_lr)

    tensors = [_to_tensors(sample) for sample in samples]
    positives = sum(float(sample.y.sum()) for sample in samples)
    total = sum(float(len(sample.y)) for sample in samples)
    pos_weight = torch.tensor([(total - positives) / max(positives, 1.0)])

    binary_loss = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    layer_loss = nn.CrossEntropyLoss(ignore_index=8)

    model.train()
    history: list[float] = []
    for epoch in range(epochs):
        epoch_loss = 0.0
        for x, edge_index, edge_attr, y, layer in tensors:
            optimiser.zero_grad()
            logits, layer_logits = model(x, edge_index, edge_attr)
            loss = binary_loss(logits, y) + settings.gnn_aux_loss_weight * layer_loss(
                layer_logits, layer
            )
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimiser.step()
            epoch_loss += float(loss.item())

        history.append(epoch_loss / max(len(tensors), 1))
        if epoch % 20 == 0:
            log.info("gnn epoch %3d  loss %.4f", epoch, history[-1])

    return model, {"final_loss": history[-1] if history else float("nan")}


def score_gnn(model: object, sample: GraphSample) -> np.ndarray:
    """Probability per node that it is a mule."""
    if not is_available():
        raise RuntimeError("PyTorch Geometric is not installed")

    model.eval()  # type: ignore[attr-defined]
    x, edge_index, edge_attr, _, _ = _to_tensors(sample)
    with torch.no_grad():
        logits, _ = model(x, edge_index, edge_attr)  # type: ignore[operator]
        return torch.sigmoid(logits).numpy().astype(np.float64)


def _to_tensors(
    sample: GraphSample,
) -> tuple[Tensor, Tensor, Tensor, Tensor, Tensor]:
    layer = np.where(sample.layer < 0, 8, np.clip(sample.layer, 0, 7))
    return (
        torch.tensor(sample.x, dtype=torch.float32),
        torch.tensor(sample.edge_index, dtype=torch.long),
        torch.tensor(sample.edge_attr, dtype=torch.float32),
        torch.tensor(sample.y, dtype=torch.float32),
        torch.tensor(layer, dtype=torch.long),
    )


def save_gnn(model: object, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), str(path))  # type: ignore[attr-defined]


def load_gnn(path: Path) -> object | None:
    if not (is_available() and path.exists()):
        return None
    try:
        model = EdgeAwareSAGE()
        model.load_state_dict(torch.load(str(path), map_location="cpu"))
        model.eval()
        return model
    except (OSError, RuntimeError, KeyError) as exc:  # pragma: no cover
        log.warning("could not load GNN: %s", exc)
        return None
