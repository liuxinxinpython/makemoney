# strategies/__init__.py

from .zigzag_wave_peaks_valleys import ZigZagWavePeaksValleysStrategy
from .chan_theory_strategy import ChanTheoryStrategy
from .global_trading_strategies import (
	MovingAverageCrossoverStrategy,
	RSIMeanReversionStrategy,
	DonchianBreakoutStrategy,
)

__all__ = [
	'ZigZagWavePeaksValleysStrategy',
	'ChanTheoryStrategy',
	'MovingAverageCrossoverStrategy',
	'RSIMeanReversionStrategy',
	'DonchianBreakoutStrategy',
]