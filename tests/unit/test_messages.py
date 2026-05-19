def test_welcome_batch_closing_includes_count():
    from apps.bot.messages import welcome_batch_closing
    text = welcome_batch_closing(5)
    assert "5" in text
    assert "09:00" in text


def test_onboarding_done_mentions_first_matches():
    from apps.bot import messages as msg
    assert "первые" in msg.ONBOARDING_DONE or "подбираю" in msg.ONBOARDING_DONE.lower()
