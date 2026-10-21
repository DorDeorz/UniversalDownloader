"""Links opened inside a YouTube Mix are reduced to the video."""

import pytest

import urls


@pytest.mark.parametrize("link, expected", [
    # A song playing inside a YouTube Mix: only the song.
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=RDdQw4w9WgXcQ&start_radio=1",
     "https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
    ("https://music.youtube.com/watch?v=abc&list=RDAMVMabc&index=3&pp=x&t=42",
     "https://music.youtube.com/watch?v=abc&t=42"),
    ("youtube.com/watch?list=RDMMxyz&v=abc", "https://youtube.com/watch?v=abc"),
    # Playlists someone made, a Mix link alone and other sites are kept.
    ("https://www.youtube.com/watch?v=abc&list=PLx123", "https://www.youtube.com/watch?v=abc&list=PLx123"),
    ("https://www.youtube.com/playlist?list=RDabc", "https://www.youtube.com/playlist?list=RDabc"),
    ("https://example.com/watch?v=abc&list=RDabc", "https://example.com/watch?v=abc&list=RDabc"),
])
def test_a_song_opened_in_a_youtube_mix_is_only_the_song(link, expected):
    assert urls.normalize_url(link) == expected
