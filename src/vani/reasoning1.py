"""
Compatibility shim for the old monolithic reasoning1.py module.

The implementation now lives in src/vani/reasoning/*:
- worker.py: session speech, realtime text bridge, background queue
- ollama.py: Qwen/Ollama fallback
- router.py: deterministic routing/dispatch
- tools/: desktop, messaging, media, code, notes, YouTube tools
- screen.py: screen OCR/vision, search/weather, learning tools
"""

from vani.reasoning import (
    ask_realtime_from_text,
    ask_realtime_from_text_thread,
    get_thinking_capability_tool,
    register_session,
    say_to_user,
    speak_to_user_from_thread,
    thinking_capability,
)
from vani.reasoning.ollama import (
    _build_qwen_prompt,
    _call_ollama_sync,
    _dispatch_intent_in_thread,
    _qwen_decide_and_run,
)
from vani.reasoning.router import (
    _classify_search_intent,
    _dispatch_intent,
    _is_learn_intent,
    _router_classify,
    _router_classify_many,
)
from vani.reasoning.screen import (
    _accessibility_snapshot,
    _browser_visible_text,
    _build_strict_screen_prompt,
    _capture_screen_mss_png,
    _fast_context_is_enough,
    _flatten_paddle_result,
    _format_local_screen_result,
    _get_fast_screen_context,
    _get_paddle_ocr,
    _is_screen_intent as _is_screen_read_intent,
    _ocr_image_macos,
    _ocr_image_paddle,
    _paddleocr_available,
    _preprocess_for_paddleocr,
    _screen_query_needs_ocr,
    get_weather,
    google_search,
    learn_name,
    learn_this,
    read_screen,
)
from vani.reasoning.shared import (
    IS_MAC,
    IS_WINDOWS,
    _compact_lines,
    _frontmost_app_name,
    _osascript,
    logger,
)
from vani.reasoning.tools.apps import (
    Play_file,
    _classify_app_intent,
    _clean_spoken_domain,
    _is_file_operation_intent,
    _looks_like_url,
    _mac_key_code,
    _mac_keystroke,
    _safe_popen,
    _verify_app_running,
    app_search,
    close_active_tab,
    close_application,
    control_volume_tool,
    folder_file,
    mouse_click_tool,
    move_cursor_tool,
    next_tab,
    open_app_smart,
    open_application,
    open_url,
    open_url_in_browser,
    open_youtube_and_play,
    press_hotkey_tool,
    press_key_tool,
    previous_tab,
    scroll_cursor_tool,
    swipe_gesture_tool,
    switch_application,
    talking_tom_control,
    type_text_tool,
)
from vani.reasoning.tools.code import (
    _call_code_llm,
    _code_search_dirs,
    _extract_block_comment,
    _find_code_file,
    _generate_java_exact_pattern,
    _generate_java_loop_pattern,
    _infer_rectangular_star_grid,
    _is_code_assist_intent,
    _iter_code_files,
    _java_col_condition,
    _java_string_literal,
    _looks_like_pattern_problem,
    _parse_code_assist_response,
    _pattern_instruction_block,
    _read_code_file,
    _strip_code_fence,
    _validate_generated_code,
    code_assist,
    write_code_to_file,
)
from vani.reasoning.tools.media import _classify_media_intent, media_control
from vani.reasoning.tools.messaging import (
    _classify_whatsapp_shortcut,
    _clean_whatsapp_message,
    _get_wa_cache,
    _normalize_whatsapp_contact,
    _parse_fast_whatsapp_command,
    _resolve_whatsapp_contact,
    _set_wa_cache,
    _split_contact_and_message_after_prefix,
    extract_contact_and_payload,
    notifications_read,
    telegram_chats,
    telegram_read,
    telegram_send,
    whatsapp_call,
    whatsapp_get_contacts,
    whatsapp_open_chat,
    whatsapp_read,
    whatsapp_send,
    whatsapp_shortcut,
)
from vani.reasoning.tools.notes import _ollama_beautify, save_note
from vani.reasoning.tools.youtube import (
    classify_youtube_query,
    youtube_control,
)


def _ensure_name(name: str, **kwargs):
    try:
        from vani.name_pronunciation import ensure_name

        return ensure_name(name, **kwargs)
    except Exception:
        return {}

