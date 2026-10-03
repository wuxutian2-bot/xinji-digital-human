from typing import Union, List, Dict, Any, Optional
import asyncio
import json
from time import perf_counter
from uuid import uuid4
from loguru import logger
import numpy as np

from .conversation_utils import (
    create_batch_input,
    process_agent_output,
    send_conversation_start_signals,
    process_user_input,
    finalize_conversation_turn,
    cleanup_conversation,
    send_conversation_end_signal,
    EMOJI_LIST,
)
from .types import WebSocketSend
from .tts_manager import TTSTaskManager
from ..chat_history_manager import store_message
from ..service_context import ServiceContext
from ..mental_health.companion_store import utc_now

# Import necessary types from agent outputs
from ..agent.output_types import SentenceOutput, AudioOutput


async def process_single_conversation(
    context: ServiceContext,
    websocket_send: WebSocketSend,
    client_uid: str,
    user_input: Union[str, np.ndarray],
    images: Optional[List[Dict[str, Any]]] = None,
    session_emoji: str = np.random.choice(EMOJI_LIST),
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    """Process a single-user conversation turn

    Args:
        context: Service context containing all configurations and engines
        websocket_send: WebSocket send function
        client_uid: Client unique identifier
        user_input: Text or audio input from user
        images: Optional list of image data
        session_emoji: Emoji identifier for the conversation
        metadata: Optional metadata for special processing flags

    Returns:
        str: Complete response text
    """
    # Create TTSTaskManager for this conversation
    tts_manager = TTSTaskManager()
    full_response = ""  # Initialize full_response here
    companion = getattr(context.agent_engine, "companion", None)
    turn_id = uuid4().hex if companion else None
    started = perf_counter()
    metadata = dict(metadata or {})
    if turn_id:
        metadata["companion_turn_id"] = turn_id
        metadata["synthetic_demo"] = bool(
            getattr(context.system_config, "synthetic_demo", False)
        )
    trial = bool(getattr(context.system_config, "trial_mode", False))
    consent = companion.get("consent", "current") if companion else None
    if trial and not (consent and consent.get("accepted")):
        await websocket_send(
            json.dumps(
                {
                    "type": "error",
                    "message": "请先打开我的心迹，阅读并选择是否参加本次体验。",
                }
            )
        )
        await send_conversation_end_signal(websocket_send, None)
        return ""
    retain = not trial or bool(consent and consent.get("retain_conversation"))
    history_uid = context.history_uid
    if companion:
        companion.put(
            "turn",
            turn_id,
            {
                "id": turn_id,
                "timestamp": utc_now(),
                "record_id": None,
                "scope": context.agent_engine._psychological_memory_scope,
                "synthetic": metadata["synthetic_demo"],
                "intent": {"primary": "unknown", "advice_preference": "unspecified"},
                "trace": {"source": "not_run", "coordination": None},
                "final_strategy": "尚未决策",
                "support_mode": context.agent_engine.support_mode,
                "history_context": None,
                "feedback": "unspecified",
                "playback": "unconfirmed",
                "generation": "pending",
                "sent_segments": [],
            },
        )

    def can_retain():
        current = companion.get("consent", "current") if companion else None
        return not trial or bool(
            current and current.get("accepted") and current.get("retain_conversation")
        )

    original_send = websocket_send
    segments = []
    announced = False

    async def tracked_send(raw):
        nonlocal announced
        payload = json.loads(raw)
        if turn_id:
            payload["turn_id"] = turn_id
            payload["history_uid"] = history_uid
            if payload.get("type") == "audio":
                turn = companion.get("turn", turn_id)
                if turn and not announced:
                    await original_send(
                        json.dumps({"type": "companion-turn", "turn": turn})
                    )
                    announced = True
                payload["segment_id"] = len(segments)
                segments.append(
                    {
                        "id": len(segments),
                        "has_audio": bool(payload.get("audio")),
                        "actions": payload.get("actions"),
                        "playback": "unconfirmed",
                        "sent": False,
                        "tts_error": payload.get("tts_error", False),
                    }
                )
                companion.update_turn(turn_id, sent_segments=list(segments))
                if payload.get("tts_error"):
                    await original_send(
                        json.dumps(
                            {
                                "type": "error",
                                "message": "语音生成失败，本轮已保留文字回复。",
                            }
                        )
                    )
        await original_send(json.dumps(payload))
        if turn_id and payload.get("type") == "audio":
            segments[-1]["sent"] = True
            # Receipts merge per segment in the store; sent does not mean played.
            companion.update_turn(turn_id, sent_segments=list(segments))

    if companion:
        websocket_send = tracked_send

    try:
        # Send initial signals
        await send_conversation_start_signals(websocket_send)
        logger.info(f"New Conversation Chain {session_emoji} started!")

        # Process user input
        input_text = await process_user_input(
            user_input, context.asr_engine, websocket_send
        )

        # Create batch input
        batch_input = create_batch_input(
            input_text=input_text,
            images=images,
            from_name=context.character_config.human_name,
            metadata=metadata,
        )

        # Store user message (check if we should skip storing to history)
        skip_history = (
            metadata.get("skip_history", False) or not retain or not can_retain()
        )
        if context.history_uid and not skip_history:
            store_message(
                conf_uid=context.character_config.conf_uid,
                history_uid=context.history_uid,
                role="human",
                content=input_text,
                name=context.character_config.human_name,
            )

        if skip_history:
            logger.debug("Skipping storing user input to history (proactive speak)")

        if not trial:
            logger.info(f"User input: {input_text}")
        if images:
            logger.info(f"With {len(images)} images")

        try:
            # agent.chat yields Union[SentenceOutput, Dict[str, Any]]
            agent_output_stream = context.agent_engine.chat(batch_input)

            async for output_item in agent_output_stream:
                if (
                    isinstance(output_item, dict)
                    and output_item.get("type") == "tool_call_status"
                ):
                    # Handle tool status event: send WebSocket message
                    output_item["name"] = context.character_config.character_name
                    logger.debug(f"Sending tool status update: {output_item}")

                    await websocket_send(json.dumps(output_item))

                elif isinstance(output_item, (SentenceOutput, AudioOutput)):
                    # Handle SentenceOutput or AudioOutput
                    response_part = await process_agent_output(
                        output=output_item,
                        character_config=context.character_config,
                        live2d_model=context.live2d_model,
                        tts_engine=context.tts_engine,
                        websocket_send=websocket_send,  # Pass websocket_send for audio/tts messages
                        tts_manager=tts_manager,
                        translate_engine=context.translate_engine,
                    )
                    # Ensure response_part is treated as a string before concatenation
                    response_part_str = (
                        str(response_part) if response_part is not None else ""
                    )
                    full_response += response_part_str  # Accumulate text response
                else:
                    logger.warning(
                        f"Received unexpected item type from agent chat stream: {type(output_item)}"
                    )
                    logger.debug(f"Unexpected item content: {output_item}")

        except Exception as e:
            if companion:
                companion.update_turn(
                    turn_id, generation="failed", error_type=type(e).__name__
                )
                companion.event("conversation_failed", outcome=type(e).__name__)
            logger.exception(
                f"Error processing agent response stream: {e}"
            )  # Log with stack trace
            await websocket_send(
                json.dumps(
                    {
                        "type": "error",
                        "message": "对话服务暂时不可用，请稍后重试。",
                    }
                )
            )
            # full_response will contain partial response before error
        # --- End processing agent response ---

        await finalize_conversation_turn(
            tts_manager=tts_manager,
            websocket_send=websocket_send,
            client_uid=client_uid,
        )

        if (
            context.history_uid == history_uid
            and history_uid
            and full_response
            and not skip_history
            and can_retain()
        ):
            store_message(
                conf_uid=context.character_config.conf_uid,
                history_uid=context.history_uid,
                role="ai",
                content=full_response,
                name=context.character_config.character_name,
                avatar=context.character_config.avatar,
                turn_id=turn_id,
            )
            if not trial:
                logger.info(f"AI response: {full_response}")

        if companion:
            companion.event(
                "conversation_finished",
                duration_ms=round((perf_counter() - started) * 1000),
            )
            await original_send(json.dumps({"type": "companion-refresh"}))

        return full_response  # Return accumulated full_response

    except asyncio.CancelledError:
        if companion:
            companion.update_turn(turn_id, playback="interrupted")
            companion.event("conversation_interrupted")
        logger.info(f"🤡👍 Conversation {session_emoji} cancelled because interrupted.")
        raise
    except Exception as e:
        if companion:
            companion.update_turn(
                turn_id, generation="failed", error_type=type(e).__name__
            )
            companion.event("conversation_failed", outcome=type(e).__name__)
        logger.exception(f"Error in conversation chain: {type(e).__name__}: {e}")
        await websocket_send(
            json.dumps(
                {"type": "error", "message": "本轮服务出现错误，请重试或使用文字输入。"}
            )
        )
        await send_conversation_end_signal(websocket_send, None)
        raise
    finally:
        cleanup_conversation(tts_manager, session_emoji)
