from __future__ import annotations

import asyncio
import ast
import logging
import os
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any

from client.plugins.base import PluginBase

logger = logging.getLogger(__name__)


class Plugin(PluginBase):
    name = "coder"
    description = "Code generation, execution, analysis, linting, formatting"
    version = "1.0.0"
    author = "Beta"

    def __init__(self, config: Any = None) -> None:
        super().__init__(config)
        self._work_dir = Path(os.environ.get("CODE_WORK_DIR", "./workspace")).resolve()
        self._work_dir.mkdir(parents=True, exist_ok=True)
        self._timeout = 30

    async def execute(self, action: str = "run", **kw: Any) -> dict[str, Any]:
        actions = {
            "run": self._run,
            "run_file": self._run_file,
            "write": self._write,
            "read": self._read,
            "lint": self._lint,
            "format": self._format,
            "analyze": self._analyze,
            "list_files": self._list_files,
            "shell": self._shell,
            "pip_install": self._pip_install,
        }
        fn = actions.get(action)
        if not fn:
            return {"error": f"Unknown action: {action}", "available": list(actions.keys())}
        return await fn(**kw)

    async def _run(self, code: str = "", language: str = "python", **kw: Any) -> dict:
        if not code:
            return {"error": "code required"}

        if language == "python":
            return await self._run_python(code)
        elif language in ("bash", "sh", "shell"):
            return await self._run_bash(code)
        elif language == "javascript":
            return await self._run_node(code)
        else:
            return {"error": f"Unsupported language: {language}"}

    async def _run_python(self, code: str) -> dict:
        tmp = Path(tempfile.mktemp(suffix=".py", dir=str(self._work_dir)))
        tmp.write_text(code, encoding="utf-8")
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                [sys.executable, str(tmp)],
                capture_output=True, text=True, timeout=self._timeout,
                cwd=str(self._work_dir),
            )
            return {
                "language": "python",
                "stdout": result.stdout[:5000],
                "stderr": result.stderr[:2000],
                "returncode": result.returncode,
                "success": result.returncode == 0,
                "file": str(tmp),
            }
        except subprocess.TimeoutExpired:
            return {"error": f"Execution timed out ({self._timeout}s)", "language": "python"}
        finally:
            tmp.unlink(missing_ok=True)

    async def _run_bash(self, code: str) -> dict:
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                code, shell=True, capture_output=True, text=True,
                timeout=self._timeout, cwd=str(self._work_dir),
            )
            return {
                "language": "bash",
                "stdout": result.stdout[:5000],
                "stderr": result.stderr[:2000],
                "returncode": result.returncode,
                "success": result.returncode == 0,
            }
        except subprocess.TimeoutExpired:
            return {"error": f"Execution timed out ({self._timeout}s)"}

    async def _run_node(self, code: str) -> dict:
        tmp = Path(tempfile.mktemp(suffix=".js", dir=str(self._work_dir)))
        tmp.write_text(code, encoding="utf-8")
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                ["node", str(tmp)],
                capture_output=True, text=True, timeout=self._timeout,
                cwd=str(self._work_dir),
            )
            return {
                "language": "javascript",
                "stdout": result.stdout[:5000],
                "stderr": result.stderr[:2000],
                "returncode": result.returncode,
                "success": result.returncode == 0,
                "file": str(tmp),
            }
        except FileNotFoundError:
            return {"error": "Node.js not installed"}
        except subprocess.TimeoutExpired:
            return {"error": f"Execution timed out ({self._timeout}s)"}
        finally:
            tmp.unlink(missing_ok=True)

    async def _run_file(self, path: str = "", args: list[str] | None = None, **kw: Any) -> dict:
        if not path:
            return {"error": "path required"}

        file_path = self._work_dir / path
        if not file_path.exists():
            return {"error": f"File not found: {path}"}

        ext = file_path.suffix.lower()
        cmd_map = {".py": [sys.executable], ".js": ["node"], ".sh": ["bash"],
                    ".rb": ["ruby"], ".go": ["go", "run"]}

        if ext not in cmd_map:
            return {"error": f"Unsupported file type: {ext}"}

        cmd = cmd_map[ext] + [str(file_path)] + (args or [])
        try:
            result = await asyncio.to_thread(
                subprocess.run, cmd, capture_output=True, text=True,
                timeout=self._timeout, cwd=str(self._work_dir),
            )
            return {
                "file": path, "stdout": result.stdout[:5000],
                "stderr": result.stderr[:2000], "returncode": result.returncode,
                "success": result.returncode == 0,
            }
        except subprocess.TimeoutExpired:
            return {"error": f"Execution timed out ({self._timeout}s)"}

    async def _write(self, path: str = "", content: str = "", **kw: Any) -> dict:
        if not path:
            return {"error": "path required"}

        file_path = self._work_dir / path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        return {"path": str(file_path), "size": len(content), "lines": content.count("\n") + 1}

    async def _read(self, path: str = "", max_lines: int = 500, **kw: Any) -> dict:
        if not path:
            return {"error": "path required"}

        file_path = self._work_dir / path
        if not file_path.exists():
            return {"error": f"File not found: {path}"}

        content = file_path.read_text(encoding="utf-8", errors="replace")
        lines = content.split("\n")
        truncated = len(lines) > max_lines
        return {
            "path": path, "content": "\n".join(lines[:max_lines]),
            "total_lines": len(lines), "truncated": truncated,
            "size": len(content),
        }

    async def _lint(self, path: str = "", **kw: Any) -> dict:
        file_path = self._work_dir / path
        if not file_path.exists():
            return {"error": f"File not found: {path}"}

        issues = []
        try:
            content = file_path.read_text(encoding="utf-8")
            tree = ast.parse(content, filename=path)
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    if not node.returns and not node.name.startswith("_"):
                        issues.append({
                            "line": node.lineno, "type": "missing_return_type",
                            "message": f"Function '{node.name}' missing return type annotation",
                        })
                    if len(node.args.args) > 5:
                        issues.append({
                            "line": node.lineno, "type": "too_many_args",
                            "message": f"Function '{node.name}' has {len(node.args.args)} args (>5)",
                        })
                elif isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id.isupper():
                            pass
        except SyntaxError as e:
            issues.append({"line": e.lineno or 0, "type": "syntax_error", "message": str(e)})

        return {"path": path, "issues": issues, "count": len(issues)}

    async def _format(self, path: str = "", **kw: Any) -> dict:
        file_path = self._work_dir / path
        if not file_path.exists():
            return {"error": f"File not found: {path}"}

        try:
            result = await asyncio.to_thread(
                subprocess.run,
                [sys.executable, "-m", "black", "--quiet", str(file_path)],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode == 0:
                content = file_path.read_text(encoding="utf-8")
                return {"path": path, "status": "formatted", "lines": content.count("\n") + 1}
            return {"error": result.stderr[:500]}
        except FileNotFoundError:
            return {"error": "black not installed (pip install black)"}
        except subprocess.TimeoutExpired:
            return {"error": "Format timed out"}

    async def _analyze(self, code: str = "", **kw: Any) -> dict:
        if not code:
            return {"error": "code required"}

        analysis = {"functions": [], "classes": [], "imports": [], "complexity": "low"}

        try:
            tree = ast.parse(code)
            lines_of_code = len(code.split("\n"))

            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    args = len(node.args.args)
                    has_return = any(isinstance(n, ast.Return) for n in ast.walk(node))
                    analysis["functions"].append({
                        "name": node.name, "args": args, "line": node.lineno,
                        "has_return": has_return,
                    })
                elif isinstance(node, ast.ClassDef):
                    methods = [n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
                    analysis["classes"].append({
                        "name": node.name, "methods": len(methods), "line": node.lineno,
                    })
                elif isinstance(node, (ast.Import, ast.ImportFrom)):
                    module = getattr(node, "module", None) or ""
                    for alias in node.names:
                        analysis["imports"].append(alias.name if not module else f"{module}.{alias.name}")

            total_complexity = len(analysis["functions"]) + len(analysis["classes"]) * 2
            if total_complexity > 20:
                analysis["complexity"] = "high"
            elif total_complexity > 8:
                analysis["complexity"] = "medium"

            analysis["lines"] = lines_of_code
            analysis["summary"] = (
                f"{len(analysis['functions'])} functions, "
                f"{len(analysis['classes'])} classes, "
                f"{len(analysis['imports'])} imports, "
                f"{lines_of_code} lines, complexity: {analysis['complexity']}"
            )
        except SyntaxError as e:
            analysis["error"] = f"Syntax error: {e}"

        return analysis

    async def _list_files(self, path: str = "", **kw: Any) -> dict:
        target = self._work_dir / path if path else self._work_dir
        if not target.exists():
            return {"error": f"Directory not found: {path}"}

        items = []
        for item in sorted(target.iterdir()):
            stat = item.stat()
            items.append({
                "name": item.name,
                "type": "dir" if item.is_dir() else "file",
                "size": stat.st_size,
                "path": str(item.relative_to(self._work_dir)),
            })
        return {"path": path or ".", "items": items, "count": len(items)}

    async def _shell(self, command: str = "", **kw: Any) -> dict:
        if not command:
            return {"error": "command required"}

        try:
            result = await asyncio.to_thread(
                subprocess.run,
                command, shell=True, capture_output=True, text=True,
                timeout=self._timeout, cwd=str(self._work_dir),
            )
            return {
                "command": command, "stdout": result.stdout[:5000],
                "stderr": result.stderr[:2000], "returncode": result.returncode,
                "success": result.returncode == 0,
            }
        except subprocess.TimeoutExpired:
            return {"error": f"Command timed out ({self._timeout}s)"}

    async def _pip_install(self, package: str = "", **kw: Any) -> dict:
        if not package:
            return {"error": "package required"}

        try:
            result = await asyncio.to_thread(
                subprocess.run,
                [sys.executable, "-m", "pip", "install", package],
                capture_output=True, text=True, timeout=120,
            )
            return {
                "package": package, "success": result.returncode == 0,
                "output": result.stdout[-2000:] if result.returncode == 0 else result.stderr[-2000:],
            }
        except subprocess.TimeoutExpired:
            return {"error": "Installation timed out (120s)"}
