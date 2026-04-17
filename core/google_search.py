#!/usr/bin/env python3
"""
google_search.py - 用web_search抓取竞品实时价格和评分
弥补高德API不提供价格数据的问题，混合模式更准确

用法:
    from core.google_search import search_hotel_prices, search_hotel_reviews

支持:
- 搜索酒店实时OTA价格（携程/Booking/Agoda）
- 抓取用户评分和评价数量
"""

import sys
sys.path.insert(0, '/root/.openclaw/workspace')

import re
import requests
from typing import List, Dict, Optional, Tuple
from urllib.parse import quote_plus

GOOGLE_SEARCH_URL = "https://www.google.com/search"

def search_hotel_info(hotel_name: str, nearby: str = "") -> Optional[str]:
    """搜索酒店信息，返回HTML内容"""
    query = f"{hotel_name}"
    if nearby:
        query += f" {nearby}"
    query += " 价格 评分"
    encoded_query = quote_plus(query)
    url = f"{GOOGLE_SEARCH_URL}?q={encoded_query}"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            return resp.text
        return None
    except Exception as e:
        print(f"[WARN] Google search failed: {e}")
        return None

def extract_price_from_html(html: str) -> Optional[int]:
    """从搜索结果HTML提取价格"""
    # 匹配¥数字, $数字, RMB数字
    price_patterns = [
        r'¥\s*(\d{3,4})',
        r'RMB\s*(\d{3,4})',
        r'NT\s*(\d{3,4})',
        r'(\d{3,4})\s*元',
        r'from\s*[\$£]\s*(\d{2,3})',  # USD/GBP
    ]

    for pattern in price_patterns:
        matches = re.findall(pattern, html, re.IGNORECASE)
        if matches:
            # 取第一个匹配
            try:
                return int(matches[0])
            except:
                continue
    return None

def extract_rating_from_html(html: str) -> Tuple[Optional[float], Optional[int]]:
    """从搜索结果提取评分和评价数"""
    # 匹配 "4.5分 (1,234 评价)"
    rating_patterns = [
        r'(\d\.\d)\s*分\s*\((\d+(?:,\d+)?)\s*评价',
        r'(\d\.\d)\s*/\s*5\s*\((\d+(?:,\d+)?)\s*,',
        r'rating\s*(\d\.\d)\s*\((\d+)\)',
    ]

    for pattern in rating_patterns:
        matches = re.findall(pattern, html, re.IGNORECASE)
        if matches:
            try:
                rating = float(matches[0][0])
                count_str = matches[0][1].replace(',', '')
                count = int(count_str)
                return rating, count
            except:
                continue
    return None, None

def search_hotel_prices_and_rating(hotel_name: str, city: str = "") -> Dict:
    """
    搜索酒店的价格和评分
    返回: {
        "price": Optional[int],  # 估算平日价格
        "rating": Optional[float],  # 用户评分
        "review_count": Optional[int],  # 评价数
        "success": bool,
    }
    """
    html = search_hotel_info(hotel_name, city)
    if not html:
        return {"success": False}

    price = extract_price_from_html(html)
    rating, review_count = extract_rating_from_html(html)

    return {
        "success": True,
        "price": price,
        "rating": rating,
        "review_count": review_count,
        "html": html,  # 保留原始html备用
    }

def search_competitor_list(competitor_names: List[str], city: str = "") -> List[Dict]:
    """批量搜索竞品信息"""
    results = []
    for name in competitor_names:
        result = search_hotel_prices_and_rating(name, city)
        result["name"] = name
        results.append(result)
    return results

if __name__ == "__main__":
    # 测试
    if len(sys.argv) > 1:
        hotel = sys.argv[1]
        city = sys.argv[2] if len(sys.argv) > 2 else ""
        result = search_hotel_prices_and_rating(hotel, city)
        print(result)
