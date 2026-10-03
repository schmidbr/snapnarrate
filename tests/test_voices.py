from snap_narrate.providers.elevenlabs import Voice


def test_voice_details_are_readable() -> None:
    voice = Voice.from_api(
        {
            "voice_id": "abc",
            "name": "Clyde",
            "category": "premade",
            "labels": {"accent": "american", "age": "middle_aged", "gender": "male", "use_case": "narration"},
            "preview_url": "https://example.com/clyde.mp3",
        }
    )
    assert voice.details == "American · Middle aged · Male · Narration"
    assert voice.preview_url.endswith(".mp3")


def test_cloned_voice_is_labelled_and_nameless_voice_gets_a_name() -> None:
    assert Voice.from_api({"voice_id": "x", "name": "My narrator", "category": "cloned"}).details == "Cloned"
    assert Voice.from_api({"voice_id": "y", "name": ""}).name == "Unnamed voice"
