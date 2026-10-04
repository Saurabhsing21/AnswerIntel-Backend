from app.providers.fake import FakeAIProvider


def test_fake_provider():

    provider = FakeAIProvider()

    response = provider.ask(
        prompt="What are the best productivity tools?",
        model="test-model",
    )

    assert response.provider == "fake"
    assert response.model == "test-model"
    assert response.prompt == "What are the best productivity tools?"
    assert response.text
    assert response.raw_response["fake"] is True