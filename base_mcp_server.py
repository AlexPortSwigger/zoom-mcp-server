#!/usr/bin/env python3
"""
Base MCP Server Class
Provides common functionality and best practices for all MCP servers.
"""

import asyncio
import json
import logging
import os
import sys
import traceback
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

import httpx
from dotenv import load_dotenv
from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.types import Resource, Tool, JSONRPCMessage
from pydantic import AnyUrl


class BaseMCPServer(ABC):
    """
    Base class for all MCP servers providing:
    - Standardized logging
    - Environment variable handling
    - Error handling with retry logic
    - Health checks
    - Token refresh patterns
    - Consistent tool registration
    """

    def __init__(self, server_name: str, description: str):
        self.server_name = server_name
        self.description = description
        self.server = Server(server_name)
        self.logger = self._setup_logging()
        self.client = None  # For HTTP requests

        # Load environment variables
        self._load_environment()

        # Initialize server capabilities
        self._register_handlers()

        self.logger.info(f"Initialized {server_name} MCP server")

    def _setup_logging(self) -> logging.Logger:
        """Set up consistent logging across all servers"""
        logger = logging.getLogger(self.server_name)
        logger.setLevel(logging.INFO)

        # Logs directory: respect ZOOM_LOG_DIR if set (useful for bundled installs
        # where the extension directory may be read-only or wiped on update).
        log_dir_env = os.getenv("ZOOM_LOG_DIR")
        if log_dir_env:
            log_dir = Path(os.path.expanduser(log_dir_env))
        else:
            log_dir = Path(__file__).parent / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)

        # File handler
        file_handler = logging.FileHandler(log_dir / f"{self.server_name}.log")
        file_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        file_handler.setFormatter(file_formatter)

        # Console handler
        console_handler = logging.StreamHandler(sys.stderr)
        console_formatter = logging.Formatter(
            '%(name)s - %(levelname)s - %(message)s'
        )
        console_handler.setFormatter(console_formatter)

        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

        return logger

    def _load_environment(self):
        """Load environment variables with consistent error handling"""
        # Look for .env in the same directory as this file
        env_path = Path(__file__).parent / ".env"
        if env_path.exists():
            load_dotenv(env_path)
            self.logger.info("Loaded environment variables from .env file")
        else:
            self.logger.warning("No .env file found, relying on system environment")

    def _register_handlers(self):
        """Register common MCP handlers"""
        @self.server.list_resources()
        async def handle_list_resources() -> List[Resource]:
            """List available resources"""
            try:
                return await self.list_resources()
            except Exception as e:
                self.logger.error(f"Error listing resources: {e}")
                return []

        @self.server.list_tools()
        async def handle_list_tools() -> List[Tool]:
            """List available tools"""
            try:
                return await self.list_tools()
            except Exception as e:
                self.logger.error(f"Error listing tools: {e}")
                return []

        @self.server.call_tool()
        async def handle_call_tool(name: str, arguments: dict) -> List[Dict[str, Any]]:
            """Handle tool calls with error handling and logging"""
            start_time = datetime.now()
            self.logger.info(f"Tool call: {name} with args: {arguments}")

            try:
                result = await self.call_tool(name, arguments)
                duration = (datetime.now() - start_time).total_seconds()
                self.logger.info(f"Tool {name} completed in {duration:.2f}s")
                return result

            except Exception as e:
                duration = (datetime.now() - start_time).total_seconds()
                self.logger.error(f"Tool {name} failed after {duration:.2f}s: {e}")
                self.logger.error(traceback.format_exc())

                return [{
                    "type": "text",
                    "text": f"Error executing {name}: {str(e)}"
                }]

    async def _http_request_with_retry(
        self,
        method: str,
        url: str,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        **kwargs
    ) -> httpx.Response:
        """Make HTTP request with exponential backoff retry logic"""
        if not self.client:
            self.client = httpx.AsyncClient(timeout=30.0)

        last_exception = None

        for attempt in range(max_retries + 1):
            try:
                response = await self.client.request(method, url, **kwargs)
                self.logger.debug(f"{method} {url} -> {response.status_code}")

                if response.status_code == 429:
                    retry_after = int(response.headers.get('retry-after', retry_delay))
                    self.logger.warning(f"Rate limited, waiting {retry_after}s")
                    await asyncio.sleep(retry_after)
                    continue

                if response.status_code >= 500 and attempt < max_retries:
                    wait_time = retry_delay * (2 ** attempt)
                    self.logger.warning(f"Server error {response.status_code}, retrying in {wait_time}s")
                    await asyncio.sleep(wait_time)
                    continue

                return response

            except httpx.RequestError as e:
                last_exception = e
                if attempt < max_retries:
                    wait_time = retry_delay * (2 ** attempt)
                    self.logger.warning(f"Request failed (attempt {attempt + 1}), retrying in {wait_time}s: {e}")
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    self.logger.error(f"Request failed after {max_retries + 1} attempts: {e}")
                    raise

        raise last_exception

    def get_required_env_var(self, var_name: str) -> str:
        """Get required environment variable with helpful error message"""
        value = os.getenv(var_name)
        if not value:
            error_msg = f"Required environment variable {var_name} not found. Please set it in your .env file."
            self.logger.error(error_msg)
            raise ValueError(error_msg)
        return value

    def get_optional_env_var(self, var_name: str, default: str = "") -> str:
        """Get optional environment variable with default"""
        return os.getenv(var_name, default)

    async def health_check(self) -> Dict[str, Any]:
        """Perform health check - override in subclasses for specific checks"""
        return {
            "status": "healthy",
            "server": self.server_name,
            "timestamp": datetime.now().isoformat()
        }

    async def cleanup(self):
        """Clean up resources on shutdown"""
        if self.client:
            await self.client.aclose()
            self.logger.info("HTTP client closed")
        self.logger.info(f"{self.server_name} server cleanup completed")

    # OAuth support methods

    def setup_oauth(self, oauth_handler):
        """Set up OAuth handler for this server"""
        self.oauth_handler = oauth_handler
        self.logger.info(f"OAuth handler configured for {self.server_name}")

    async def ensure_oauth_authenticated(self) -> bool:
        """Ensure OAuth authentication is valid"""
        if not hasattr(self, 'oauth_handler'):
            self.logger.error("No OAuth handler configured")
            return False
        try:
            return await self.oauth_handler.ensure_authenticated()
        except Exception as e:
            self.logger.error(f"OAuth authentication failed: {e}")
            return False

    async def make_oauth_request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """Make an OAuth-authenticated HTTP request"""
        if not hasattr(self, 'oauth_handler'):
            raise ValueError("No OAuth handler configured")
        return await self.oauth_handler.make_authenticated_request(method, url, **kwargs)

    def get_oauth_headers(self) -> Dict[str, str]:
        """Get OAuth authorization headers"""
        if not hasattr(self, 'oauth_handler'):
            raise ValueError("No OAuth handler configured")
        return self.oauth_handler.get_auth_headers()

    async def refresh_oauth_token(self) -> bool:
        """Manually refresh OAuth token"""
        if not hasattr(self, 'oauth_handler'):
            self.logger.error("No OAuth handler configured")
            return False
        try:
            return await self.oauth_handler.refresh_access_token()
        except Exception as e:
            self.logger.error(f"Token refresh failed: {e}")
            return False

    # Abstract methods that subclasses must implement

    @abstractmethod
    async def list_resources(self) -> List[Resource]:
        pass

    @abstractmethod
    async def list_tools(self) -> List[Tool]:
        pass

    @abstractmethod
    async def call_tool(self, name: str, arguments: dict) -> List[Dict[str, Any]]:
        pass

    # Helper methods

    def create_text_result(self, text: str) -> List[Dict[str, Any]]:
        return [{"type": "text", "text": text}]

    def create_json_result(self, data: Any) -> List[Dict[str, Any]]:
        return [{"type": "text", "text": json.dumps(data, indent=2, ensure_ascii=False)}]

    def create_error_result(self, error: str) -> List[Dict[str, Any]]:
        return [{"type": "text", "text": f"Error: {error}"}]

    def validate_required_args(self, arguments: dict, required_args: List[str]) -> None:
        missing_args = [arg for arg in required_args if arg not in arguments]
        if missing_args:
            raise ValueError(f"Missing required arguments: {', '.join(missing_args)}")

    def run_server(self):
        """Run the MCP server"""
        self.logger.info(f"Starting {self.server_name} MCP server...")
        try:
            asyncio.run(self._run_server_async())
        except Exception as e:
            self.logger.error(f"Server error: {e}")
            self.logger.error(traceback.format_exc())
            sys.exit(1)

    async def _run_server_async(self):
        """Internal async method to run the MCP server"""
        import mcp.server.stdio
        from mcp.server.models import InitializationOptions
        import signal

        def signal_handler(signum, frame):
            self.logger.info(f"Received signal {signum}, shutting down...")
            asyncio.create_task(self.cleanup())
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
            from mcp.server import NotificationOptions
            await self.server.run(
                read_stream,
                write_stream,
                InitializationOptions(
                    server_name=self.server_name,
                    server_version="1.0.0",
                    capabilities=self.server.get_capabilities(
                        notification_options=NotificationOptions(),
                        experimental_capabilities={}
                    )
                )
            )
