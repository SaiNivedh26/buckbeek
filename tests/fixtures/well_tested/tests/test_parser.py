from src.parser import parse, parse_line

def test_parse_line():
    assert parse_line("key = value") == ("key", "value")

def test_parse_multiple():
    result = parse("a = 1\nb = 2\n# comment\n")
    assert result == {"a": "1", "b": "2"}

def test_parse_empty():
    assert parse("") == {}
