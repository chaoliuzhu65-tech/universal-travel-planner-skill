#!/usr/bin/env python3
"""
feishu_push.py - 飞书消息推送模块
每日监测报告生成后，自动推送到指定飞书群/用户

支持:
- 推送文本消息（包含报告链接）
- 推送卡片消息（美观格式）
- 需要环境变量: FEISHU_APP_ID, FEISHU_APP_SECRET
"""

import os
import json
import requests
from typing import Optional, List, Dict


class FeishuPush:
    """飞书消息推送"""

    def __init__(self, app_id: str = None, app_secret: str = None):
        self.app_id = app_id or os.environ.get("FEISHU_APP_ID")
        self.app_secret = app_secret or os.environ.get("FEISHU_APP_SECRET")
        self._token = None

    def get_access_token(self) -> Optional[str]:
        """获取tenant access token"""
        if self._token:
            return self._token
        if not self.app_id or not self.app_secret:
            print("[WARN] FEISHU_APP_ID 或 FEISHU_APP_SECRET 未配置，无法推送")
            return None

        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        resp = requests.post(url, json={
            "app_id": self.app_id,
            "app_secret": self.app_secret
        }, timeout=10)
        data = resp.json()
        if data.get("code") == 0:
            self._token = data.get("tenant_access_token")
            return self._token
        print(f"[ERROR] 获取token失败: {data}")
        return None

    def push_text(self, chat_id: str, text: str) -> bool:
        """推送文本消息到群/用户

        chat_id 格式:
        - 群: oc_xxxxxx
        - 用户: ou_xxxxxx
        """
        token = self.get_access_token()
        if not token:
            return False

        url = "https://open.feishu.cn/open-apis/im/v1/messages"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8"
        }
        params = {"receive_id_type": "chat_id" if chat_id.startswith("oc_") else "open_id"}

        content = json.dumps({"text": text})
        body = {
            "receive_id": chat_id,
            "msg_type": "text",
            "content": content
        }

        resp = requests.post(url, headers=headers, params=params, json=body, timeout=10)
        data = resp.json()
        if data.get("code") == 0:
            print(f"[OK] 消息推送成功: {chat_id}")
            return True
        else:
            print(f"[ERROR] 推送失败: {data}")
            return False

    def push_card(self, chat_id: str, title: str, content: str,
                  doc_url: str = None) -> bool:
        """推送交互式卡片消息，美观格式"""

        token = self.get_access_token()
        if not token:
            return False

        # 构建卡片元素
        elements = [
            {
                "tag": "div",
                "text": {
                    "content": content,
                    "tag": "lark_md"
                }
            }
        ]

        if doc_url:
            elements.append({"tag": "hr"})
            elements.append({
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {
                            "content": "点击查看完整报告",
                            "tag": "lark_md"
                        },
                        "url": doc_url,
                        "type": "default"
                    }
                ]
            })

        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {
                    "content": title,
                    "tag": "plain_text"
                },
                "template": "blue"
            },
            "elements": elements
        }

        url = "https://open.feishu.cn/open-apis/im/v1/messages"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8"
        }
        params = {"receive_id_type": "chat_id" if chat_id.startswith("oc_") else "open_id"}

        content = json.dumps(card)
        body = {
            "receive_id": chat_id,
            "msg_type": "interactive",
            "content": content
        }

        resp = requests.post(url, headers=headers, params=params, json=body, timeout=15)
        data = resp.json()
        if data.get("code") == 0:
            print(f"[OK] 卡片推送成功: {chat_id}")
            return True
        else:
            print(f"[ERROR] 卡片推送失败: {data}")
            return False


def push_daily_report(chat_id: str, hotel_name: str, target_date: str,
                      standard_price: int, rate: float,
                      doc_url: str = None) -> bool:
    """推送每日监测报告通知"""

    push = FeishuPush()
    if not push.get_access_token():
        return False

    title = f"📊 {hotel_name} - {target_date} 价格监测日报"
    content = (
        f"**酒店**: {hotel_name}\n\n"
        f"**目标日期**: {target_date}\n\n"
        f"**推荐价格**: ¥{standard_price} (涨幅 +{rate}%)\n\n"
        f"数据已更新，请查看完整报告"
    )

    return push.push_card(chat_id, title, content, doc_url)

