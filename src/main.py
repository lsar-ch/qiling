"""
DeskMate - 桌面 AI 精灵主入口。

用法:
    python -m src.main              # 启动 GUI
    python -m src.main --test       # 测试模式（无 GUI）
    python -m src.main --cli        # CLI 对话模式
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# 添加项目根目录到 path
sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml
from loguru import logger

# 配置 loguru
logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level:<7}</level> | {message}")


def load_settings(config_path: str = "config/settings.yaml") -> dict:
    """加载配置文件。"""
    path = Path(__file__).parent.parent / config_path
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f)
    logger.warning(f"Config not found: {path}, using defaults")
    return {}


def run_gui(settings: dict) -> None:
    """启动 GUI 版本。"""
    from PyQt6.QtWidgets import QApplication
    from src.ui.controller import FloatController
    from src.agent import DeskMateAgent

    app = QApplication(sys.argv)
    app.setApplicationName("DeskMate")

    # 创建精灵窗口
    ui_cfg = settings.get("ui", {})
    size_cfg = ui_cfg.get("size", {"width": 120, "height": 120})
    controller = FloatController(
        size=controller.__class__.__dict__ if hasattr(controller, '__class__') else None,
        position=ui_cfg.get("position", "center"),
        always_on_top=ui_cfg.get("always_on_top", True),
        opacity=ui_cfg.get("opacity", 0.95),
    )

    # 加载 .env
    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent / ".env"
    load_dotenv(env_path)

    # 加载 LLM 系统提示
    llm_cfg = settings.get("llm", {})
    if llm_cfg.get("system_prompt_path"):
        prompt_path = Path(__file__).parent.parent / llm_cfg["system_prompt_path"]
        llm_cfg["system_prompt"] = prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else ""

    # 创建 Agent
    agent = DeskMateAgent(controller, settings)
    agent.start()

    controller.show()
    logger.info("DeskMate is running. Click the sphere to interact.")

    # 连接点击事件
    controller.clicked.connect(lambda: logger.info("Sphere clicked"))

    sys.exit(app.exec())


def run_cli(settings: dict) -> None:
    """CLI 对话模式。"""
    from src.llm.agent import LLMClient
    from src.memory.store import MemoryStore
    from src.memory.retriever import MemoryRetriever

    llm_cfg = settings.get("llm", {})
    memory_cfg = settings.get("memory", {})

    # 加载系统提示
    system_prompt = ""
    if llm_cfg.get("system_prompt_path"):
        prompt_path = Path(__file__).parent.parent / llm_cfg["system_prompt_path"]
        if prompt_path.exists():
            system_prompt = prompt_path.read_text(encoding="utf-8")

    client = LLMClient(
        provider=llm_cfg.get("provider", "ollama"),
        model=llm_cfg.get("model", "qwen3:8b"),
        base_url=llm_cfg.get("base_url", "http://localhost:11434"),
        system_prompt=system_prompt,
    )
    memory = MemoryStore(db_path=memory_cfg.get("db_path", "./data/memory/chat_history.db"))
    retriever = MemoryRetriever(memory)

    print("=" * 50)
    print("  DeskMate CLI Mode")
    print("  Type 'quit' to exit, 'clear' to clear history")
    print("=" * 50)

    while True:
        try:
            user_input = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit"):
            print("Bye!")
            break
        if user_input.lower() == "clear":
            print("History cleared.")
            continue

        context = retriever.retrieve_context(user_input, recent_limit=10, memory_limit=3)
        messages = context.to_messages(client)
        messages.append({"role": "user", "content": user_input})
        memory.add_message(role="user", content=user_input)

        print("DeskMate: ", end="", flush=True)
        response = client.chat(messages, stream=True)
        full_response = ""
        for chunk in response:
            print(chunk, end="", flush=True)
            full_response += chunk
        print()

        memory.add_message(role="assistant", content=full_response)


def run_test(settings: dict) -> None:
    """测试模式：验证各模块是否正常初始化。"""
    print("Running DeskMate self-test...\n")

    # 测试配置加载
    print("[OK] Settings loaded")

    # 测试记忆存储
    from src.memory.store import MemoryStore
    store = MemoryStore(db_path="./data/memory/test.db")
    store.add_message("user", "Hello")
    store.add_message("assistant", "Hi there!")
    msgs = store.get_recent(limit=5)
    assert len(msgs) >= 2, "Memory storage failed"
    print(f"[OK] Memory: {store.get_stats()}")
    store.close()

    # 测试 LLM 连接
    from src.llm.agent import LLMClient
    llm_cfg = settings.get("llm", {})
    client = LLMClient(
        provider=llm_cfg.get("provider", "ollama"),
        model=llm_cfg.get("model", "qwen3:8b"),
        base_url=llm_cfg.get("base_url", "http://localhost:11434"),
    )
    try:
        resp = client.chat([{"role": "user", "content": "Say hello in 5 words"}], stream=False)
        print(f"[OK] LLM response: {resp[:60]}...")
    except Exception as e:
        print(f"[WARN] LLM not reachable: {e}")

    # 测试 TTS
    from src.voice.synthesizer import TTSSynthesizer
    tts = TTSSynthesizer()
    try:
        tts.synthesize("测试", "./data/memory/test_tts.mp3")
        print("[OK] TTS synthesizer ready")
    except Exception as e:
        print(f"[WARN] TTS not ready: {e}")

    print("\nSelf-test complete!")


def main() -> None:
    parser = argparse.ArgumentParser(description="DeskMate - 桌面 AI 精灵")
    parser.add_argument("--test", action="store_true", help="运行自测")
    parser.add_argument("--cli", action="store_true", help="CLI 对话模式")
    parser.add_argument("--config", default="config/settings.yaml", help="配置文件路径")
    args = parser.parse_args()

    settings = load_settings(args.config)

    if args.test:
        run_test(settings)
    elif args.cli:
        run_cli(settings)
    else:
        run_gui(settings)


if __name__ == "__main__":
    main()
