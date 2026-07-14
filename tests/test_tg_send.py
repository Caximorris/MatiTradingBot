from __future__ import annotations


def test_tg_send_passes_keyboard_and_keeps_it_on_html_fallback(monkeypatch):
    import tools.tg_send as mod

    calls = []
    monkeypatch.setattr(mod, "tg_credentials", lambda: ("token", "chat"))

    def fake_api(method, params, timeout=15):
        calls.append((method, params))
        if len(calls) == 1:
            raise RuntimeError("bad html")
        return {"ok": True}

    monkeypatch.setattr(mod, "tg_api", fake_api)
    assert mod.tg_send("<b>x</b>", parse_mode="HTML", reply_markup="{menu}") is True
    assert calls[0][1]["reply_markup"] == "{menu}"
    assert calls[1][1]["reply_markup"] == "{menu}"
    assert "parse_mode" not in calls[1][1]
