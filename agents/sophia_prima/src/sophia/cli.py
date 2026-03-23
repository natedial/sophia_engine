"""CLI entry point for Sophia."""

import asyncio
import uuid

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style
from pylon import PreflightResult, Pylon, PylonConfig

from sophia.agent import AgentConfig, SophiaAgent
from sophia.context import ConversationContext
from sophia.config import get_settings
from sophia.events import AgentEvent, EventType
from sophia.llm.types import ToolCall


console = Console()

prompt_style = Style.from_dict({
    "prompt": "cyan bold",
})


async def chat_loop(agent: SophiaAgent, session_id: str | None = None) -> None:
    """Run the interactive chat loop, consuming the agent's event stream."""
    context = ConversationContext(session_id=session_id or str(uuid.uuid4()))

    session: PromptSession[str] = PromptSession(
        history=FileHistory(".sophia_history"),
        style=prompt_style,
    )

    canvas_line = (
        f"\nDashboard: [link]{agent.settings.canvas_dashboard_url}?canvas={agent.canvas_id}[/link]"
        if agent.canvas_id
        else ""
    )
    console.print(
        Panel(
            f"[bold cyan]{agent.personality.name}[/bold cyan] is ready.\n"
            "Type your message and press Enter. Use Ctrl+D or 'exit' to quit."
            f"{canvas_line}",
            title="Sophia",
            border_style="cyan",
        )
    )

    while True:
        try:
            user_input = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: session.prompt("\n[You] ", style=prompt_style),
            )

            if not user_input.strip():
                continue

            if user_input.strip().lower() in ("exit", "quit", "bye", "bibi"):
                console.print("\n[dim]Goodbye![/dim]")
                break

            # Stream events from the agent
            text_buffer = ""
            tools_used: list[str] = []
            streaming = False

            async for event in agent.run(user_input, context):
                if event.type == EventType.MESSAGE_START:
                    # Print the agent name header before first content
                    console.print(f"\n[bold cyan][{agent.personality.name}][/bold cyan]")
                    streaming = True
                    text_buffer = ""

                elif event.type == EventType.MESSAGE_DELTA:
                    # Print text incrementally (plain text during streaming)
                    text = event.data["text"]
                    text_buffer += text
                    print(text, end="", flush=True)

                elif event.type == EventType.MESSAGE_END:
                    if streaming and text_buffer:
                        # End the streamed line, then render full markdown
                        print()  # newline after streaming
                    elif not text_buffer:
                        # Non-streaming or no deltas arrived — render full response
                        msg = event.data["message"]
                        if msg.content:
                            console.print(Markdown(msg.content))
                    streaming = False

                elif event.type == EventType.SKILL_ACTIVATED:
                    skill_name = event.data.get("name", "unknown")
                    reason = event.data.get("reason", "match")
                    console.print(
                        f"\n  [dim]Skill activated: {skill_name} ({reason})[/dim]"
                    )

                elif event.type == EventType.TOOL_EXECUTION_START:
                    tc: ToolCall = event.data["tool_call"]
                    console.print(f"\n  [dim]Calling {tc.name}...[/dim]", end="")

                elif event.type == EventType.TOOL_EXECUTION_UPDATE:
                    text = event.data.get("text", "")
                    if text:
                        console.print(f" [dim]{text}[/dim]", end="")

                elif event.type == EventType.TOOL_EXECUTION_END:
                    tc = event.data["tool_call"]
                    is_error = event.data.get("is_error", False)
                    if is_error:
                        console.print(f" [red]error[/red]")
                    else:
                        console.print(f" [green]done[/green]")
                    tools_used.append(_format_tool_call(tc))

                elif event.type == EventType.SUBAGENT_START:
                    name = event.data.get("name", "subagent")
                    task = event.data.get("task", "")
                    display_task = task[:80] + "..." if len(task) > 80 else task
                    console.print(f"\n  [dim]Subagent start: {name} - {display_task}[/dim]")

                elif event.type == EventType.SUBAGENT_END:
                    name = event.data.get("name", "subagent")
                    summary = event.data.get("summary", "")
                    display_summary = summary[:120] + "..." if len(summary) > 120 else summary
                    console.print(f"\n  [dim]Subagent done: {name} - {display_summary}[/dim]")

                elif event.type == EventType.SUBAGENT_ERROR:
                    name = event.data.get("name", "subagent")
                    error = event.data.get("error", "unknown error")
                    console.print(f"\n  [yellow]Subagent error ({name}): {error}[/yellow]")

            # Show tool summary after all events
            if tools_used:
                console.print(f"\n[dim]Tools used: {' → '.join(tools_used)}[/dim]")

        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye![/dim]")
            break
        except Exception as e:
            console.print(f"\n[red]Error: {e}[/red]")


def _format_tool_call(tc: ToolCall) -> str:
    """Format a tool call for display."""
    if tc.input:
        param_strs = []
        for key, value in list(tc.input.items())[:2]:
            if isinstance(value, str):
                display_val = value[:30] + "..." if len(value) > 30 else value
                param_strs.append(f"{key}='{display_val}'")
            else:
                param_strs.append(f"{key}={value}")
        return f"{tc.name}({', '.join(param_strs)})"
    return f"{tc.name}()"


def _create_provider(settings):
    """Create an LLM provider based on settings."""
    provider_name = getattr(settings, "llm_provider", "openai").lower().strip()

    if provider_name == "anthropic":
        from sophia.llm.anthropic_provider import AnthropicProvider
        return AnthropicProvider(api_key=settings.anthropic_api_key)
    if provider_name == "openai":
        from sophia.llm.openai_provider import OpenAIProvider
        return OpenAIProvider(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
        )
    if provider_name == "groq":
        from sophia.llm.groq_provider import GroqProvider
        return GroqProvider(
            api_key=settings.groq_api_key,
            base_url=settings.groq_base_url,
        )

    raise ValueError(
        f"Unsupported LLM provider: '{provider_name}'. "
        "Supported providers: anthropic, openai, groq"
    )


async def setup_pylon(settings) -> tuple[Pylon, PreflightResult]:
    """Initialize Pylon gateway and run pre-flight checks."""
    config = PylonConfig(
        scrivener_url=settings.scrivener_base_url,
        arithmos_url=settings.arithmos_base_url,
        canvas_url=settings.canvas_base_url,
        tholos_url=settings.tholos_base_url,
        fed_tracker_url=settings.fed_tracker_url,
        readwise_cli_path=settings.readwise_cli_path,
        readwise_cli_config_path=settings.readwise_cli_config_path,
        brave_base_url=settings.brave_base_url,
        brave_api_key=settings.brave_api_key,
    )
    pylon = Pylon(config)

    preflight = await pylon.preflight()

    for status in preflight.services.values():
        if status.healthy:
            console.print(f"  [green]✓[/green] {status.status_summary}")
        else:
            console.print(f"  [yellow]✗[/yellow] {status.status_summary}")

    if preflight.unavailable_tools:
        console.print(
            f"  [yellow]![/yellow] Disabled tools: {', '.join(preflight.unavailable_tools)}"
        )

    return pylon, preflight


async def init_canvas(session_id: str, pylon: Pylon, preflight: PreflightResult, settings) -> str | None:
    """Create a canvas for this session if the canvas service is healthy."""
    canvas_status = preflight.services.get("canvas")
    if not canvas_status or not canvas_status.healthy:
        return None

    try:
        data = await pylon.canvas.create_canvas(
            session_id=session_id,
            name="Analysis Dashboard",
        )
        canvas_id: str = data["id"]
        dashboard_url = f"{settings.canvas_dashboard_url}?canvas={canvas_id}"
        console.print(
            f"  [green]✓[/green] Dashboard ready: [link={dashboard_url}]{dashboard_url}[/link]"
        )
        return canvas_id
    except Exception as e:
        console.print(f"  [yellow]![/yellow] Could not create canvas: {e}")
        return None


async def async_main() -> None:
    """Async main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Sophia - Conversational Agent")
    parser.add_argument("--config", help="Path to .env configuration file")
    args = parser.parse_args()

    settings = get_settings()

    # Validate API key for selected provider
    provider_name = getattr(settings, "llm_provider", "openai").lower().strip()
    if provider_name == "anthropic" and not settings.anthropic_api_key:
        console.print(
            "[red]Error: ANTHROPIC_API_KEY not set.[/red]\n"
            "Please set it in your .env file or environment."
        )
        return
    if provider_name == "openai" and not settings.openai_api_key:
        console.print(
            "[red]Error: OPENAI_API_KEY not set.[/red]\n"
            "Please set it in your .env file or environment."
        )
        return
    if provider_name == "groq" and not settings.groq_api_key:
        console.print(
            "[red]Error: GROQ_API_KEY not set.[/red]\n"
            "Please set it in your .env file or environment."
        )
        return

    # Create provider
    try:
        provider = _create_provider(settings)
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        return

    # Setup Pylon gateway with pre-flight checks
    console.print("[dim]Running pre-flight checks...[/dim]")
    pylon, preflight = await setup_pylon(settings)

    # Create a canvas for this session (if canvas service is available)
    session_id = str(uuid.uuid4())
    canvas_id = await init_canvas(session_id, pylon, preflight, settings)

    # Create agent
    agent = SophiaAgent(
        provider=provider,
        settings=settings,
        pylon=pylon,
        preflight_result=preflight,
        canvas_id=canvas_id,
    )

    try:
        await chat_loop(agent, session_id=session_id)
    finally:
        await provider.close()


def main() -> None:
    """Main entry point."""
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
