"""
predictor.py — Lightweight statistical/ML predictors used by the AI monitor.

Deliberately dependency-light (pure Python + optional numpy) so the whole
simulator boots instantly with no model downloads: linear-trend
extrapolation for utilization forecasting, z-score anomaly detection for
outlier process behaviour, and confidence scoring for every prediction —
matching the "confidence scores" requirement without pretending a toy
in-memory simulator needs a full deep-learning stack.

(A PyTorch/production upgrade path is documented in docs/AI_DESIGN.md —
this module's interfaces are designed to be swapped for a trained model
without touching call sites.)
"""

from __future__ import annotations
import math
from collections import deque


class TrendPredictor:
    """Simple ordinary-least-squares linear regression over a rolling
    window, used to forecast CPU/memory utilization a few ticks ahead."""

    def __init__(self, window: int = 30):
        self.window = window
        self.history: deque = deque(maxlen=window)

    def add_sample(self, value: float):
        self.history.append(value)

    def _fit(self):
        n = len(self.history)
        if n < 2:
            return 0.0, (self.history[-1] if self.history else 0.0)
        xs = list(range(n))
        ys = list(self.history)
        mean_x = sum(xs) / n
        mean_y = sum(ys) / n
        num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
        den = sum((x - mean_x) ** 2 for x in xs) or 1e-9
        slope = num / den
        intercept = mean_y - slope * mean_x
        return slope, intercept

    def forecast(self, ticks_ahead: int = 20) -> dict:
        n = len(self.history)
        slope, intercept = self._fit()
        future_x = n - 1 + ticks_ahead
        predicted = slope * future_x + intercept
        predicted = max(0.0, min(100.0, predicted))
        # confidence shrinks with fewer samples and higher volatility
        volatility = self._volatility()
        confidence = max(0.05, min(0.95, (n / self.window) * (1 - min(volatility / 40, 0.8))))
        return {
            "predicted_value": round(predicted, 1),
            "slope_per_tick": round(slope, 3),
            "confidence": round(confidence, 2),
            "ticks_ahead": ticks_ahead,
        }

    def _volatility(self) -> float:
        if len(self.history) < 2:
            return 0.0
        mean = sum(self.history) / len(self.history)
        return math.sqrt(sum((v - mean) ** 2 for v in self.history) / len(self.history))

    def ticks_until_threshold(self, threshold: float) -> int | None:
        slope, intercept = self._fit()
        n = len(self.history)
        if slope <= 0.0001:
            return None
        current_x = n - 1
        current_y = slope * current_x + intercept
        if current_y >= threshold:
            return 0
        ticks = (threshold - current_y) / slope
        return max(0, round(ticks))


class AnomalyDetector:
    """Z-score based anomaly detection across a metric stream per entity
    (e.g. per-process CPU usage, memory footprint growth)."""

    def __init__(self, window: int = 25, z_threshold: float = 2.3):
        self.window = window
        self.z_threshold = z_threshold
        self.streams: dict[str, deque] = {}

    def observe(self, key: str, value: float) -> dict:
        stream = self.streams.setdefault(key, deque(maxlen=self.window))
        stream.append(value)
        if len(stream) < 5:
            return {"is_anomaly": False, "z_score": 0.0, "confidence": 0.1}
        mean = sum(stream) / len(stream)
        std = math.sqrt(sum((v - mean) ** 2 for v in stream) / len(stream)) or 1e-6
        z = (value - mean) / std
        is_anomaly = abs(z) > self.z_threshold
        confidence = min(0.97, abs(z) / (self.z_threshold * 2))
        return {"is_anomaly": is_anomaly, "z_score": round(z, 2), "confidence": round(confidence, 2)}
