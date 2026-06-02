from vani.router.intent_classifier import (
    classify_media_intent,
    parse_fast_whatsapp_command,
    router_classify,
    router_classify_many,
)


def test_router_classifies_google_search():
    assert router_classify("google karo best cafe delhi") == (
        "GOOGLE_SEARCH",
        "best cafe delhi",
    )
    assert router_classify("google par latest ai news search karo") == (
        "GOOGLE_SEARCH",
        "latest ai news",
    )
    assert router_classify("udemy.com par ML course search karo") == (
        "GOOGLE_SEARCH",
        "udemy.com par ml course search karo",
    )
    assert router_classify("search two sum on leetcode.com") == (
        "GOOGLE_SEARCH",
        "search two sum on leetcode.com",
    )
    assert router_classify("cyber security article search karo on google") == (
        "GOOGLE_SEARCH",
        "cyber security article",
    )


def test_router_classifies_url_open():
    assert router_classify("open example dot com") == ("OPEN_URL", "example.com")
    assert router_classify("open youtube dot com") == ("OPEN_URL", "youtube.com")
    assert router_classify("vani open google dot com") == ("OPEN_URL", "google.com")


def test_router_opens_youtube_search_for_open_site_query():
    assert router_classify("open youtube khat") == (
        "OPEN_URL",
        "https://www.youtube.com/results?search_query=khat",
    )
    assert router_classify("open youtube and search khat") == (
        "OPEN_URL",
        "https://www.youtube.com/results?search_query=khat",
    )
    assert router_classify("search khat on youtube") == (
        "OPEN_URL",
        "https://www.youtube.com/results?search_query=khat",
    )
    assert router_classify("youtube search lo fi coding music") == (
        "OPEN_URL",
        "https://www.youtube.com/results?search_query=lo+fi+coding+music",
    )
    assert router_classify("youtube par arijit singh dhundo") == (
        "OPEN_URL",
        "https://www.youtube.com/results?search_query=arijit+singh",
    )
    assert router_classify("yt pe arijit singh dhundho") == (
        "OPEN_URL",
        "https://www.youtube.com/results?search_query=arijit+singh",
    )
    assert router_classify("youtube pe lofi coding music khoj kar do") == (
        "OPEN_URL",
        "https://www.youtube.com/results?search_query=lofi+coding+music",
    )


def test_router_classifies_youtube_play_deterministically():
    assert router_classify("play shape of you on youtube") == (
        "YOUTUBE_PLAY",
        "shape of you",
    )
    assert router_classify("youtube par shape of you chalao") == (
        "YOUTUBE_PLAY",
        "shape of you",
    )
    assert router_classify("aree wani youtube par haule haule se play kardo") == (
        "YOUTUBE_PLAY",
        "haule haule se",
    )
    assert router_classify("open youtube and play zulfein") == (
        "YOUTUBE_PLAY",
        "zulfein",
    )
    assert router_classify("youtube pe kesariya laga do") == (
        "YOUTUBE_PLAY",
        "kesariya",
    )
    assert router_classify("raanjhanaa song youtube par suna do") == (
        "YOUTUBE_PLAY",
        "raanjhanaa song",
    )


def test_router_opens_searchable_site_home_without_query():
    assert router_classify("open youtube") == ("APP_OPEN", "youtube")


def test_router_opens_whatsapp_and_leetcode_in_browser():
    assert router_classify("open whatsapp") == ("OPEN_URL", "https://web.whatsapp.com")
    assert router_classify("open leetcode two sum") == (
        "OPEN_URL",
        "https://leetcode.com/problemset/?search=two+sum",
    )


def test_router_opens_common_web_apps_and_searches():
    assert router_classify("open chatgpt") == ("OPEN_URL", "https://chatgpt.com")
    assert router_classify("open chat gpt python decorators") == (
        "OPEN_URL",
        "https://chatgpt.com/?q=python+decorators",
    )
    assert router_classify("open google latest ai news") == (
        "OPEN_URL",
        "https://www.google.com/search?q=latest+ai+news",
    )
    assert router_classify("search latest ai news on google") == (
        "GOOGLE_SEARCH",
        "latest ai news",
    )
    assert router_classify("github search langchain agents") == (
        "OPEN_URL",
        "https://github.com/search?q=langchain+agents",
    )
    assert router_classify("github pe langchain agents khojo") == (
        "OPEN_URL",
        "https://github.com/search?q=langchain+agents",
    )
    assert router_classify("open google.com latest ai news") == (
        "OPEN_URL",
        "https://www.google.com/search?q=latest+ai+news",
    )
    assert router_classify("open hacker rank arrays") == (
        "OPEN_URL",
        "https://www.hackerrank.com/search?term=arrays",
    )
    assert router_classify("open linkedln rudra") == (
        "OPEN_URL",
        "https://www.linkedin.com/search/results/all/?keywords=rudra",
    )
    assert router_classify("open instagram virat") == (
        "OPEN_URL",
        "https://www.instagram.com/explore/search/keyword/?q=virat",
    )
    assert router_classify("open web whatsapp") == ("OPEN_URL", "https://web.whatsapp.com")
    assert router_classify("wani chatgpt kholo") == ("OPEN_URL", "https://chatgpt.com")
    assert router_classify("are vani leetcode two sum open karo") == (
        "OPEN_URL",
        "https://leetcode.com/problemset/?search=two+sum",
    )
    assert router_classify("udemy.com ML courses") == (
        "OPEN_URL",
        "https://www.udemy.com/courses/search/?q=ml+courses",
    )
    assert router_classify("open udemy.com ML courses") == (
        "OPEN_URL",
        "https://www.udemy.com/courses/search/?q=ml+courses",
    )


def test_router_keeps_desktop_apps_as_app_open():
    assert router_classify("open chrome") == ("APP_OPEN", "chrome")
    assert router_classify("open brave") == ("APP_OPEN", "brave")
    assert router_classify("open safari") == ("APP_OPEN", "safari")
    assert router_classify("open telegram") == ("APP_OPEN", "telegram")


def test_fast_whatsapp_send_drops_surname_noise():
    parsed = parse_fast_whatsapp_command("message shrey upadhaya hii")
    assert parsed == {
        "intent": "WHATSAPP_SEND",
        "contact": "shrey",
        "message": "hii",
        "call_type": "",
    }


def test_router_classifies_whatsapp_call():
    assert router_classify("video call to Muskan") == (
        "WHATSAPP_CALL",
        ("muskan", "video"),
    )


def test_media_classifier_does_not_steal_specific_play_request():
    assert classify_media_intent("play Shape of You on youtube") is None
    assert router_classify("youtube pause") == ("MEDIA_CONTROL", "pause")


def test_router_classifies_screen_read():
    assert router_classify("meri screen dekho") == ("SCREEN_READ", "meri screen dekho")


def test_router_classifies_compound_actions_for_parallel_dispatch():
    assert router_classify_many("search hackerrank on google & play khat on youtube") == [
        ("OPEN_URL", "https://www.google.com/search?q=hackerrank", "search hackerrank on google"),
        ("YOUTUBE_PLAY", "khat", "play khat on youtube"),
    ]
    assert router_classify_many("github pe langchain agents khojo aur youtube pe khat laga do") == [
        ("OPEN_URL", "https://github.com/search?q=langchain+agents", "github pe langchain agents khojo"),
        ("YOUTUBE_PLAY", "khat", "youtube pe khat laga do"),
    ]
    assert router_classify_many("open youtube and play zulfein") == []
