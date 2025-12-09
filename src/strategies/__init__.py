# strategies/__init__.py

from .zigzag_wave_peaks_valleys import ZigZagWavePeaksValleysStrategy, ZIGZAG_STRATEGY_PARAMETERS
from .chan_theory_strategy import ChanTheoryStrategy, CHAN_STRATEGY_PARAMETERS
from .global_trading_strategies import (
	MovingAverageCrossoverStrategy,
	RSIMeanReversionStrategy,
	DonchianBreakoutStrategy,
	PARAMETERS_BY_STRATEGY,
)

__all__ = [
	'ZigZagWavePeaksValleysStrategy',
	'ChanTheoryStrategy',
	'MovingAverageCrossoverStrategy',
	'RSIMeanReversionStrategy',
	'DonchianBreakoutStrategy',
	'ZIGZAG_STRATEGY_PARAMETERS',
	'CHAN_STRATEGY_PARAMETERS',
	'PARAMETERS_BY_STRATEGY',
]
