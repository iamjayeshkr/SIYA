from vani.browser.control import (
    _build_yt_search_query,
    _site_search_or_home_url,
    start_youtube_play_background,
)


def test_site_search_and_home_resolution():
    cases = [
        ("google", "https://www.google.com"),
        ("google machine learning", "q=machine+learning"),
        ("google par machine learning search karo", "q=machine+learning"),
        ("google.com par python dhundo", "q=python"),
        ("search karo python on google", "q=python"),
        ("search latest ai news on google", "q=latest+ai+news"),
        ("youtube arijit singh", "search_query=arijit+singh"),
        ("youtube par zulfiqar play karo", "search_query=zulfiqar"),
        ("open youtube and search lo fi coding music", "search_query=lo+fi+coding+music"),
        ("search khat on youtube", "search_query=khat"),
        ("yt pe arijit singh dhundho", "search_query=arijit+singh"),
        ("youtube pe lofi coding music khoj kar do", "search_query=lofi+coding+music"),
        ("amazon par shoes dhundo", "k=shoes"),
        ("github par langchain search karo", "q=langchain"),
        ("github search langchain agents", "q=langchain+agents"),
        ("github pe langchain agents khojo", "q=langchain+agents"),
        ("reddit machine learning", "q=machine+learning"),
        ("linkedin par software engineer dhundo", "keywords=software+engineer"),
        ("open youtube", "youtube.com"),
        ("whatsapp kholo", "web.whatsapp.com"),
    ]

    for command, expected in cases:
        assert expected in (_site_search_or_home_url(command) or "")


def test_youtube_intent_stripping_and_search_query():
    cases = [
        ("youtube par khat play karo", "khat song"),
        ("open youtube and play zulfein", "zulfein song"),
        ("youtube pe kesariya laga do", "kesariya song"),
        ("raanjhanaa song youtube par suna do", "raanjhanaa song"),
        ("dildarian laga do", "dildarian song"),
        ("play Sidhu Moosewala", "sidhu moosewala song"),
        ("dooron dooron se song", "dooron dooron se song"),
    ]

    for command, expected in cases:
        assert _build_yt_search_query(command).lower() == expected


def test_youtube_play_runs_ytdlp_resolution_in_background(monkeypatch):
    from vani.browser import control

    opened = []

    def fake_get_youtube_url(query):
        assert query == "kesariya"
        return "https://www.youtube.com/watch?v=abc123XYZ09"

    def fake_open_url(url, browser_hint="default", new_window=False):
        opened.append((url, browser_hint, new_window))
        return "opened"

    monkeypatch.setattr(control, "get_youtube_url", fake_get_youtube_url)
    monkeypatch.setattr(control, "_open_url", fake_open_url)

    reply = start_youtube_play_background("kesariya", browser="default")
    assert "YouTube par dhoondh rahi hoon" in reply

    for job in list(control._youtube_play_jobs):
        job.join(timeout=2)

    assert opened == [("https://www.youtube.com/watch?v=abc123XYZ09&autoplay=1", "default", False)]
