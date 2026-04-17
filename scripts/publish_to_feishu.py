#!/usr/bin/env python3
"""
publish_to_feishu.py - 将生成的Markdown报告批量发布到飞书云文档
用法:
python scripts/publish_to_feishu.py --input output/README.md [--folder-token your-folder-token]

说明:
- 读取README.md中的报告列表
- 逐个读取Markdown文件，创建为飞书云文档
- 在指定飞书云文件夹中创建，不会覆盖原有文件（同名会创建新版本）
- 需要飞书API授权，通过环境变量 FEISHU_APP_ID FEISHU_APP_SECRET 读取
"""

import os
import sys
import argparse
import re
import json
import requests
from typing import List, Dict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class FeishuClient:
    """飞书API客户端（飞书云文档创建）- 正确块格式"""

    def __init__(self, app_id: str, app_secret: str):
        self.app_id = app_id
        self.app_secret = app_secret
        self._token = None

    def get_access_token(self) -> str:
        """获取tenant access token"""
        if self._token:
            return self._token
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        resp = requests.post(url, json={
            "app_id": self.app_id,
            "app_secret": self.app_secret
        })
        data = resp.json()
        if data.get("code") == 0:
            self._token = data.get("tenant_access_token")
            return self._token
        raise ValueError(f"get token failed: {data}")

    def create_doc(self, title: str, markdown: str, folder_token: str = None) -> dict:
        """
        创建飞书云文档 - 正确格式
        飞书API要求:
        {
          "title": "xxx",
          "content": {
            "blocks": [
              {"type": "markdown", "content": "..."}
            ]
          }
        }
        """
        token = self.get_access_token()
        url = "https://open.feishu.cn/open-apis/docx/v1/documents"

        # 将markdown按行分割，每个段落一个block
        lines = markdown.split('\n')
        blocks = []
        current_paragraph = []

        for line in lines:
            if line.strip() == '':
                if current_paragraph:
                    content = '\n'.join(current_paragraph)
                    blocks.append({
                        "type": "markdown",
                        "content": content
                    })
                    current_paragraph = []
            else:
                current_paragraph.append(line)

        # 最后一段
        if current_paragraph:
            content = '\n'.join(current_paragraph)
            blocks.append({
                "type": "markdown",
                "content": content
            })

        body = {
            "title": title,
            "content": {
                "blocks": blocks
            },
        }
        if folder_token:
            body["folder_token"] = folder_token

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8"
        }

        # 整个body一起json序列化，避免双重编码
        resp = requests.post(url, json=body, headers=headers)
        return resp.json()


def parse_readme(readme_path: str) -> List[Dict]:
    """解析README.md获取所有报告"""
    results = []
    with open(readme_path, "r", encoding="utf-8") as f:
        for line in f:
            # 匹配表格行 "| 酒店名称 | HTML最新 | 生成日期 | 推荐价格 |"
            m = re.match(r'^\|\s*\[([^\]]+)\]\(([^)]+)\)\s*\|.*¥(\d+)\s*\|', line.strip())
            if m:
                name = m.group(1)
                md_path = m.group(2)
                price = int(m.group(3))
                # 相对于readme的路径
                base_dir = os.path.dirname(readme_path)
                full_md_path = os.path.join(base_dir, md_path)
                results.append({
                    "name": name,
                    "md_path": full_md_path,
                    "recommended_price": price,
                })
    # 如果没匹配到，尝试旧格式
    if not results:
        with open(readme_path, "r", encoding="utf-8") as f:
            for line in f:
                m = re.match(r'^- \[(.*?)\]\((.*?)\).*¥(\d+)', line.strip())
                if m:
                    name = m.group(1)
                    md_path = m.group(2)
                    price = int(m.group(3))
                    base_dir = os.path.dirname(readme_path)
                    full_md_path = os.path.join(base_dir, md_path)
                    results.append({
                        "name": name,
                        "md_path": full_md_path,
                        "recommended_price": price,
                    })
    return results


def read_markdown(md_path: str) -> str:
    """读取Markdown内容"""
    with open(md_path, "r", encoding="utf-8") as f:
        return f.read()


def main():
    parser = argparse.ArgumentParser(description="批量发布报告到飞书云文档")
    parser.add_argument("--input", "-i", required=True, help="README.md 文件路径")
    parser.add_argument("--folder-token", "-f", required=False, default="", help="飞书云文件夹token（可选，不传则放根目录）")
    args = parser.parse_args()

    # 读取飞书凭证
    app_id = os.environ.get("FEISHU_APP_ID")
    app_secret = os.environ.get("FEISHU_APP_SECRET")
    if not app_id or not app_secret:
        print("❌ 请设置环境变量 FEISHU_APP_ID 和 FEISHU_APP_SECRET")
        sys.exit(1)

    # 解析报告列表
    reports = parse_readme(args.input)
    print(f"📋 找到 {len(reports)} 份报告准备发布")

    # 初始化客户端
    client = FeishuClient(app_id, app_secret)

    # 逐个发布
    created_urls = []
    for i, report in enumerate(reports):
        print(f"\n🚀 发布 ({i+1}/{len(reports)}): {report['name']}")
        content = read_markdown(report["md_path"])
        title = f"{report['name']} 竞品价格分析报告"

        try:
            result = client.create_doc(title, content, args.folder_token if args.folder_token else None)
            print(f"   API返回: {json.dumps(result, indent=2, ensure_ascii=False)}")
            if result.get("code") == 0:
                if "data" in result and "document" in result["data"] and "document_id" in result["data"]["document"]:
                    doc_id = result['data']['document']['document_id']
                    doc_url = f"https://www.feishu.cn/docx/{doc_id}"
                    print(f"   ✅ 成功: {doc_url}")
                    created_urls.append({
                        "name": report['name'],
                        "url": doc_url,
                    })
                else:
                    print(f"   ⚠️ 创建成功，但无法获取URL")
            else:
                print(f"   ❌ 失败: {result.get('msg')}")
        except Exception as e:
            print(f"   ❌ 异常: {e}")
            import traceback
            traceback.print_exc()
            continue

    # 输出汇总
    print("\n" + "="*60)
    print(f"✅ 发布完成！共成功 {len(created_urls)}/{len(reports)} 份")
    print("\n📋 发布结果：")
    for item in created_urls:
        print(f"- {item['name']}: {item['url']}")
    print("="*60)


if __name__ == "__main__":
    main()
