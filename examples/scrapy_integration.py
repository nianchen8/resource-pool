"""Scrapy 集成示例 —— 自定义 Middleware 接入资源池三池

将 resource-pool 的 UA 池、DNS 池、代理池集成到 Scrapy 爬虫中，
通过 Downloader Middleware 在每次请求前自动替换资源。

使用方式::

    # settings.py
    DOWNLOADER_MIDDLEWARES = {
        'myproject.middlewares.ResourcePoolMiddleware': 543,
    }

    RESOURCE_POOL_CONFIG = {
        'ua': {'strategy': 'weighted'},
        'dns': {'strategy': 'latency_weighted'},
        'proxy': {'strategy': 'latency_weighted'},
    }

要求：Scrapy >= 2.8, resource-pool >= 0.5.0
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ── Scrapy Middleware ──────────────────────────────────────────────────
# 注：Scrapy 未列为 project 依赖，以下代码展示集成模式，
# 用户需自行 pip install scrapy 后使用。


class ResourcePoolMiddleware:
    """Scrapy Downloader Middleware —— 每次请求前自动更换资源

    功能：
    - 自动为每个请求替换 User-Agent（Header Profile 组）
    - 自动为每个请求设置代理
    - 可选：通过 DNS 池解析目标域名（自定义 DNS 解析）

    使用示例（settings.py）::

        DOWNLOADER_MIDDLEWARES = {
            'examples.scrapy_integration.ResourcePoolMiddleware': 543,
        }
    """

    def __init__(self, crawler):
        self.crawler = crawler
        self._ua_pool = None
        self._dns_pool = None
        self._proxy_pool = None
        self._init_pools()

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler)

    def _init_pools(self) -> None:
        """从 Scrapy settings 初始化资源池"""
        try:
            from resource_pool import (
                UserAgentPool, DNSResolverPool, ProxyPool,
            )
            from resource_pool import UAStrategy
            from proxy_pool import ProxyStrategy
            from dns_resolver_pool import SelectStrategy
        except ImportError:
            logger.warning("resource-pool 未安装，Middleware 将跳过资源替换")
            return

        config = self.crawler.settings.getdict("RESOURCE_POOL_CONFIG", {})

        # UA 池
        ua_cfg = config.get("ua", {})
        if ua_cfg.get("enabled", True):
            strategy = {
                "weighted": UAStrategy.WEIGHTED,
                "uniform": UAStrategy.UNIFORM,
            }.get(ua_cfg.get("strategy", "weighted"), UAStrategy.WEIGHTED)
            self._ua_pool = UserAgentPool(strategy=strategy)
            logger.info("UA 池已初始化 (strategy=%s)", strategy)

        # DNS 池
        dns_cfg = config.get("dns", {})
        if dns_cfg.get("enabled", True):
            strategy = {
                "latency_weighted": SelectStrategy.LATENCY_WEIGHTED,
                "round_robin": SelectStrategy.ROUND_ROBIN,
                "random": SelectStrategy.RANDOM,
            }.get(
                dns_cfg.get("strategy", "latency_weighted"),
                SelectStrategy.LATENCY_WEIGHTED,
            )
            self._dns_pool = DNSResolverPool(strategy=strategy)
            logger.info("DNS 池已初始化 (strategy=%s)", strategy)

        # 代理池
        proxy_cfg = config.get("proxy", {})
        if proxy_cfg.get("enabled", True):
            strategy = {
                "latency_weighted": ProxyStrategy.LATENCY_WEIGHTED,
                "round_robin": ProxyStrategy.ROUND_ROBIN,
                "random": ProxyStrategy.RANDOM,
            }.get(
                proxy_cfg.get("strategy", "latency_weighted"),
                ProxyStrategy.LATENCY_WEIGHTED,
            )
            self._proxy_pool = ProxyPool(strategy=strategy)
            # 从配置的 URL 加载代理
            proxy_url = proxy_cfg.get("load_url", "")
            if proxy_url:
                try:
                    self._proxy_pool.load_from_url(proxy_url)
                except Exception as e:
                    logger.warning("代理加载失败: %s", e)
            logger.info("代理池已初始化 (strategy=%s)", strategy)

    def process_request(self, request, spider) -> None:
        """在请求发出前替换 UA、Headers 和代理"""
        # 1. 替换 UA / Headers
        if self._ua_pool:
            try:
                headers = self._ua_pool.get_headers()
                request.headers.update(headers)
            except Exception as e:
                logger.debug("UA 替换失败: %s", e)

        # 2. 设置代理
        if self._proxy_pool:
            try:
                proxy_dict = self._proxy_pool.get_dict()
                request.meta["proxy"] = proxy_dict.get("http", "")
            except Exception as e:
                logger.debug("代理设置失败: %s", e)

        # 3. DNS 池解析（可选：仅当 spider 需要自定义 DNS 解析时启用）
        # Scrapy 默认使用系统 DNS，如需 DNS 池接管，需要额外配置
        # 此处仅做标记，实际 DNS 接管需通过 Twisted 的 resolver 实现

    def process_exception(self, request, exception, spider) -> Any:
        """请求失败时标记代理失败"""
        if self._proxy_pool and request.meta.get("proxy"):
            # 从 proxy URL 提取 host:port，标记失败
            proxy_url = request.meta["proxy"]
            try:
                # 简单解析 http://host:port
                host_port = proxy_url.split("://", 1)[-1]
                if ":" in host_port:
                    host, port_str = host_port.rsplit(":", 1)
                    self._proxy_pool.mark_failed(host, int(port_str))
                    logger.debug("已标记代理失败: %s", host)
            except Exception:
                pass
        return None

    def spider_closed(self, spider) -> None:
        """爬虫关闭时清理资源"""
        if self._dns_pool and hasattr(self._dns_pool, "close"):
            self._dns_pool.close()
        logger.info("资源池 Middleware 已清理")


# ── Scrapy Spider 示例 ────────────────────────────────────────────────
# 配合 Middleware 使用的 Spider 示例：

EXAMPLE_SPIDER = '''
import scrapy

class MySpider(scrapy.Spider):
    name = "resource_pool_demo"
    start_urls = ["https://httpbin.org/ip"]

    # settings.py 中配置：
    # DOWNLOADER_MIDDLEWARES = {
    #     'examples.scrapy_integration.ResourcePoolMiddleware': 543,
    # }

    def parse(self, response):
        yield {
            "url": response.url,
            "status": response.status,
            "ip": response.json().get("origin"),
        }
'''


# ── 运行说明 ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(__doc__)
    print("\n" + "=" * 60)
    print("此文件为集成模式参考代码，不直接运行。")
    print("请将 ResourcePoolMiddleware 复制到你的 Scrapy 项目中。")
    print("=" * 60)
