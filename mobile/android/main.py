import asyncio
import os
import threading

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput

from vani.mobile.runtime import MobileRuntime
from vani.mobile.voice import MobileVoice
from vani.mobile.realtime import MobileRealtimeSession


class VaniMobileApp(App):
    def build(self):
        os.environ.setdefault("VANI_PLATFORM", "mobile")
        self.runtime = MobileRuntime()
        self.voice = MobileVoice()
        self.session_id = "mobile-local-session"
        self.realtime = MobileRealtimeSession(
            runtime=self.runtime,
            voice=self.voice,
            session_id=self.session_id,
            on_event=self._on_realtime_event,
        )

        root = BoxLayout(orientation="vertical", padding=12, spacing=8)
        root.add_widget(Label(text="Vani Mobile", font_size=22, size_hint_y=None, height=40))

        self.chat_log = Label(
            text="Vani: Ready. Type a message.\n",
            halign="left",
            valign="top",
            size_hint_y=None,
        )
        self.chat_log.bind(width=lambda *_: self.chat_log.setter("text_size")(self.chat_log, (self.chat_log.width, None)))
        self.chat_log.bind(texture_size=lambda *_: setattr(self.chat_log, "height", self.chat_log.texture_size[1] + 20))

        scroll = ScrollView(size_hint=(1, 0.7))
        scroll.add_widget(self.chat_log)
        root.add_widget(scroll)

        self.input_box = TextInput(
            multiline=False,
            hint_text="Type your message...",
            size_hint_y=None,
            height=46,
        )
        self.input_box.bind(on_text_validate=lambda *_: self._send_message())
        root.add_widget(self.input_box)

        send_btn = Button(text="Send", size_hint_y=None, height=46)
        send_btn.bind(on_release=lambda *_: self._send_message())
        root.add_widget(send_btn)

        voice_btn = Button(text="Voice Input", size_hint_y=None, height=46)
        voice_btn.bind(on_release=lambda *_: self._voice_input())
        root.add_widget(voice_btn)

        rt_row = BoxLayout(orientation="horizontal", size_hint_y=None, height=46, spacing=6)
        rt_start = Button(text="Start Realtime")
        rt_stop = Button(text="Stop Realtime")
        rt_start.bind(on_release=lambda *_: self._start_realtime())
        rt_stop.bind(on_release=lambda *_: self._stop_realtime())
        rt_row.add_widget(rt_start)
        rt_row.add_widget(rt_stop)
        root.add_widget(rt_row)

        self.voice_status = Label(
            text=(
                f"Voice: speak={'yes' if self.voice.can_speak else 'no'}, "
                f"listen={'yes' if self.voice.can_listen else 'no'}"
            ),
            size_hint_y=None,
            height=28,
        )
        root.add_widget(self.voice_status)
        return root

    def _append_chat(self, line: str) -> None:
        self.chat_log.text += line + "\n"

    def _on_realtime_event(self, kind: str, text: str) -> None:
        if kind == "user_voice":
            self._append_chat(f"You (realtime): {text}")
        elif kind == "assistant":
            self._append_chat(f"Vani: {text}")
        else:
            self._append_chat(f"Vani: {text}")

    def _start_realtime(self) -> None:
        if not self.voice.can_listen:
            self._append_chat("Vani: Realtime unavailable (mic/STT backend missing).")
            return
        started = self.realtime.start()
        if not started:
            self._append_chat("Vani: Realtime already running.")

    def _stop_realtime(self) -> None:
        stopped = self.realtime.stop()
        if not stopped:
            self._append_chat("Vani: Realtime already stopped.")

    def _send_message(self) -> None:
        message = self.input_box.text.strip()
        if not message:
            return
        self.input_box.text = ""
        self._append_chat(f"You: {message}")
        try:
            payload = asyncio.run(self.runtime.handle_text(self.session_id, message))
            reply = (payload.get("reply") or "").strip() or "No response."
        except Exception as exc:
            reply = f"Runtime error: {exc}"
        self._append_chat(f"Vani: {reply}")
        self.voice.speak(reply)

    def _voice_input(self) -> None:
        self._append_chat("Vani: Listening...")

        def _run():
            heard = self.voice.listen_once()
            if not heard:
                self._append_chat("Vani: Voice input unavailable or not recognized.")
                return
            self._append_chat(f"You (voice): {heard}")
            try:
                payload = asyncio.run(self.runtime.handle_text(self.session_id, heard))
                reply = (payload.get("reply") or "").strip() or "No response."
            except Exception as exc:
                reply = f"Runtime error: {exc}"
            self._append_chat(f"Vani: {reply}")
            self.voice.speak(reply)

        threading.Thread(target=_run, daemon=True, name="vani-mobile-voice-input").start()


if __name__ == "__main__":
    VaniMobileApp().run()
