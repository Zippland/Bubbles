"""Weather related service helpers for Function Call handlers."""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Optional

from function.func_weather import Weather


logger = logging.getLogger(__name__)


@dataclass
class WeatherResult:
    success: bool
    message: str
    city: Optional[str] = None


def _load_city_codes() -> dict[str, str]:
    """Load mapping between city names and weather codes."""
    city_code_path = os.path.join(os.path.dirname(__file__), '..', '..', 'function', 'main_city.json')
    with open(city_code_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def get_weather_report(city_name: str) -> WeatherResult:
    """Return a weather report for a given city.

    Args:
        city_name: City provided by the user.

    Returns:
        WeatherResult containing success status and message.
    """
    city = city_name.strip()
    if not city:
        return WeatherResult(success=False, message="🤔 请告诉我你想查询哪个城市的天气")

    try:
        city_codes = _load_city_codes()
    except Exception as exc:  # pragma: no cover - IO failure is rare
        logger.error(f"加载城市代码失败: {exc}")
        return WeatherResult(success=False, message="⚠️ 抱歉，天气功能暂时不可用")

    code = city_codes.get(city)
    if not code:
        for name, value in city_codes.items():
            if city in name:
                code = value
                city = name
                break

    if not code:
        return WeatherResult(success=False, message=f"😕 找不到城市 '{city_name}' 的天气信息")

    try:
        weather_text = Weather(code).get_weather(include_forecast=True)
        return WeatherResult(success=True, message=weather_text, city=city)
    except Exception as exc:  # pragma: no cover - upstream API failure
        logger.error(f"获取天气数据失败: {exc}")
        return WeatherResult(success=False, message=f"😥 获取 {city} 天气时遇到问题")
