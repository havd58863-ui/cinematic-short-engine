import pytest
from director.storyboard import Storyboard, Shot

def shot(sid, start, end, seq):
    return Shot(shot_id=sid, sequence_number=seq, start_seconds=start, end_seconds=end, narration="line", purpose="advance story", visual_prompt="A specific cinematic image of the event", negative_prompt="blurry, malformed anatomy", subtitle_text="line")

def test_storyboard_valid_timeline():
    board = Storyboard(title="test", shots=[shot("s1", 0, 2, 1), shot("s2", 2, 4, 2)])
    board.validate_timeline()

def test_storyboard_rejects_overlap():
    board = Storyboard(title="test", shots=[shot("s1", 0, 3, 1), shot("s2", 2, 4, 2)])
    with pytest.raises(ValueError): board.validate_timeline()

def test_storyboard_rejects_duplicate_ids():
    board = Storyboard(title="test", shots=[shot("s1", 0, 2, 1), shot("s1", 2, 4, 2)])
    with pytest.raises(ValueError): board.validate_timeline()

def test_storyboard_rejects_timeline_gap():
    board = Storyboard(title="test", shots=[shot("s1", 0, 2, 1), shot("s2", 3, 4, 2)])
    with pytest.raises(ValueError): board.validate_timeline()
