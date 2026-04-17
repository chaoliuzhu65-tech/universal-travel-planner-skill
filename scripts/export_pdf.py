#!/usr/bin/env python3
"""
export_pdf.py - 将HTML报告导出为PDF
需要安装 wkhtmltopdf: apt install wkhtmltopdf

用法:
python scripts/export_pdf.py --input reports/hotel.html --output reports/hotel.pdf
"""

import argparse
import subprocess
import os


def html_to_pdf(html_path: str, pdf_path: str) -> bool:
    """使用wkhtmltopdf将HTML转换为PDF"""
    cmd = [
        "wkhtmltopdf",
        "--enable-local-file-access",
        "--page-size", "A4",
        "--margin-top", "10",
        "--margin-bottom", "10",
        "--margin-left", "10",
        "--margin-right", "10",
        html_path,
        pdf_path
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"✅ PDF已生成: {pdf_path}")
            return True
        else:
            print(f"❌ 转换失败: {result.stderr}")
            return False
    except FileNotFoundError:
        print("❌ 未找到wkhtmltopdf，请先安装: apt install wkhtmltopdf")
        return False


def batch_export(html_dir: str, output_dir: str) -> None:
    """批量导出目录下所有HTML为PDF"""
    os.makedirs(output_dir, exist_ok=True)
    count = 0
    for filename in os.listdir(html_dir):
        if filename.endswith(".html"):
            html_path = os.path.join(html_dir, filename)
            pdf_filename = filename.replace(".html", ".pdf")
            pdf_path = os.path.join(output_dir, pdf_filename)
            if html_to_pdf(html_path, pdf_path):
                count += 1
    print(f"\n📊 批量转换完成，共 {count} 个PDF")


def main():
    parser = argparse.ArgumentParser(description="HTML报告转PDF")
    parser.add_argument("--input", "-i", help="输入HTML文件或目录")
    parser.add_argument("--output", "-o", help="输出PDF文件或目录")
    args = parser.parse_args()

    if not args.input or not args.output:
        print("请提供--input和--output参数")
        return

    if os.path.isdir(args.input):
        # 批量转换
        batch_export(args.input, args.output)
    else:
        # 单个转换
        html_to_pdf(args.input, args.output)


if __name__ == "__main__":
    main()
