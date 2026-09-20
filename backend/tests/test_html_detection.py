from app.sources.common.html import looks_like_challenge


def test_captcha_library_reference_is_not_an_active_challenge() -> None:
    html = """
    <html><body><main>Book flights</main>
    <script src="https://www.google.com/recaptcha/enterprise.js"></script>
    <script>grecaptcha.enterprise.render("login-captcha", {});</script>
    </body></html>
    """
    assert looks_like_challenge(html) is False


def test_human_verification_page_is_an_active_challenge() -> None:
    assert looks_like_challenge("<h1>Verify you are human</h1>") is True
