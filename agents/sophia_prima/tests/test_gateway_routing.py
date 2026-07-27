from sophia.gateway.models import InboundMessage
from sophia.gateway.routing import BindingRule, GatewayRouter


def test_router_uses_first_matching_binding() -> None:
    router = GatewayRouter(
        bindings=[
            BindingRule(
                channel="telegram",
                account_id="default",
                peer_id="123",
                agent_id="agent_a",
                session_id="session-a",
            ),
            BindingRule(
                channel="telegram",
                account_id="default",
                agent_id="agent_b",
                session_id="session-b",
            ),
        ],
        default_agent_id="fallback",
    )
    message = InboundMessage(
        channel="telegram",
        account_id="default",
        peer_id="123",
        text="hi",
    )

    decision = router.resolve(message)

    assert decision.agent_id == "agent_a"
    assert decision.session_id == "session-a"


def test_router_uses_formatted_session_template() -> None:
    router = GatewayRouter(
        bindings=[
            BindingRule(
                channel="telegram",
                account_id="research",
                agent_id="sophia_prima",
                session_id="tg:{account_id}:{peer_id}",
            )
        ]
    )
    message = InboundMessage(
        channel="telegram",
        account_id="research",
        peer_id="9981",
        text="latest CPI",
    )

    decision = router.resolve(message)

    assert decision.session_id == "tg:research:9981"
    assert decision.agent_id == "sophia_prima"


def test_router_falls_back_to_default_route() -> None:
    router = GatewayRouter(default_agent_id="sophia_prima")
    message = InboundMessage(
        channel="telegram",
        account_id="default",
        peer_id="chat-77",
        text="hello",
    )

    decision = router.resolve(message)

    assert decision.agent_id == "sophia_prima"
    assert decision.session_id == "telegram:default:chat-77"
