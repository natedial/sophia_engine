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

from sophia.agent import ConversationContext, SophiaAgent
from sophia.config import get_settings


console = Console()

prompt_style = Style.from_dict({
    "prompt": "cyan bold",
})


async def chat_loop(agent: SophiaAgent) -> None:
    """Run the interactive chat loop."""
    context = ConversationContext(session_id=str(uuid.uuid4()))

    # Setup prompt with history
    session: PromptSession[str] = PromptSession(
        history=FileHistory(".sophia_history"),
        style=prompt_style,
    )

    console.print(
        Panel(
            f"[bold cyan]{agent.personality.name}[/bold cyan] is ready.\n"
            "Type your message and press Enter. Use Ctrl+D or 'exit' to quit.",
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

            # Get response from agent
            with console.status("[cyan]Thinking...[/cyan]"):
                response = await agent.chat(user_input, context)

            # Display response
            console.print(f"\n[bold cyan][{agent.personality.name}][/bold cyan]")
            console.print(Markdown(response.content))

            # Show tool usage if any
            if response.tool_calls:
                tools_used = []
                for tc in response.tool_calls:
                    # Format tool call with key parameters
                    tool_name = tc["name"]
                    params = tc.get("input", {})

                    # Show up to 2 most relevant parameters
                    if params:
                        param_strs = []
                        for key, value in list(params.items())[:2]:
                            if isinstance(value, str):
                                # Truncate long strings
                                display_val = value[:30] + "..." if len(value) > 30 else value
                                param_strs.append(f"{key}='{display_val}'")
                            else:
                                param_strs.append(f"{key}={value}")
                        tool_display = f"{tool_name}({', '.join(param_strs)})"
                    else:
                        tool_display = f"{tool_name}()"

                    tools_used.append(tool_display)

                console.print(f"\n[dim]Tools used: {' → '.join(tools_used)}[/dim]")

        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye![/dim]")
            break
        except Exception as e:
            console.print(f"\n[red]Error: {e}[/red]")


async def setup_pylon(settings) -> tuple[Pylon, PreflightResult]:
    """Initialize Pylon gateway and run pre-flight checks."""
    config = PylonConfig(scrivener_url=settings.scrivener_base_url)
    pylon = Pylon(config)

    # Run pre-flight checks
    preflight = await pylon.preflight()

    # Display results
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


async def async_main() -> None:
    """Async main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Sophia - Conversational Agent")
    parser.add_argument(
        "--config",
        help="Path to .env configuration file",
    )
    args = parser.parse_args()

    # Load settings
    settings = get_settings()

    # Validate API key
    if not settings.anthropic_api_key:
        console.print(
            "[red]Error: ANTHROPIC_API_KEY not set.[/red]\n"
            "Please set it in your .env file or environment."
        )
        return

    # Setup Pylon gateway with pre-flight checks
    console.print("[dim]Running pre-flight checks...[/dim]")
    pylon, preflight = await setup_pylon(settings)

    # Create agent with preflight result for graceful degradation
    agent = SophiaAgent(settings=settings, pylon=pylon, preflight_result=preflight)

    # Run chat loop
    await chat_loop(agent)


def main() -> None:
    """Main entry point."""
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
