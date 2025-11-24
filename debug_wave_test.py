#!/usr/bin/env python3

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from pathlib import Path
from src.strategies.wave_peaks_valleys import WavePeaksValleysStrategy
from src.data.data_loader import load_candles_from_sqlite
from src.rendering import render_html

def test_wave_detection():
    """测试波峰波谷检测和渲染"""

    # 设置数据库路径
    db_path = Path('src/a_share_daily.db')

    # 创建策略
    strategy = WavePeaksValleysStrategy()

    # 测试第一个股票
    import sqlite3
    conn = sqlite3.connect('src/a_share_daily.db')
    tables = conn.execute('SELECT name FROM sqlite_master WHERE type="table"').fetchall()
    table_name = tables[0][0] if tables else None

    if not table_name:
        print("No tables found")
        return

    print(f"Testing with table: {table_name}")

    # 执行检测
    result = strategy.scan_current_symbol(db_path, table_name)

    if result is None:
        print("No result returned")
        return

    markers = result.markers if hasattr(result, 'markers') else result.get('markers', [])
    print(f"Generated {len(markers)} markers")

    if markers:
        print("First marker:", markers[0])

    # 加载股票数据
    data = load_candles_from_sqlite(db_path, table_name)
    if not data:
        print("Failed to load data")
        return

    candles, volumes, instrument = data
    print(f"Loaded {len(candles)} candles")

    # 生成HTML
    html = render_html(candles, volumes, instrument, markers, [])

    # 保存HTML文件用于检查
    with open('debug_chart.html', 'w', encoding='utf-8') as f:
        f.write(html)

    print("HTML saved to debug_chart.html")

    # 检查HTML中的标记
    if '__SIGNALS__' in html:
        signals_start = html.find('__SIGNALS__') + len('__SIGNALS__')
        signals_end = html.find('", "__OVERLAYS__"', signals_start)
        if signals_end > signals_start:
            signals_json = html[signals_start:signals_end]
            print(f"Signals in HTML: {signals_json[:200]}...")

if __name__ == '__main__':
    test_wave_detection()