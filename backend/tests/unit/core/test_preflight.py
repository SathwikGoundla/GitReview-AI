import pytest
from app.core.preflight import validate_secret, check_production_cors

def test_validate_secret_missing():
    assert validate_secret("")[0] is False
    assert validate_secret(None)[0] is False

def test_validate_secret_length():
    # 31 chars
    assert validate_secret("a" * 30 + "b")[1] == "UNSAFE DEFAULT"
    # 32 chars
    assert validate_secret("a" * 31 + "b")[1] == "PASS"

def test_validate_secret_repeated():
    assert validate_secret("a" * 32)[1] == "UNSAFE DEFAULT"
    
def test_validate_secret_placeholder():
    assert validate_secret("your_shared_secret_here")[1] == "UNSAFE DEFAULT"
    
def test_validate_secret_weak_word():
    assert validate_secret("changeme")[1] == "UNSAFE DEFAULT"
    assert validate_secret("SECRET")[1] == "UNSAFE DEFAULT"
    assert validate_secret("password")[1] == "UNSAFE DEFAULT"
    
def test_validate_secret_substring_allowed():
    # Long value containing "secret" as a substring is NOT rejected
    long_secret = "a" * 16 + "secret" + "b" * 16
    assert validate_secret(long_secret)[1] == "PASS"

def test_cors_valid():
    assert check_production_cors(["chrome-extension://abcdefghijklmnopqrstuvwxyz123456"])[0] is True
    
def test_cors_missing():
    assert check_production_cors([])[0] is False
    
def test_cors_wildcard():
    assert check_production_cors(["*"])[0] is False
    
def test_cors_localhost():
    assert check_production_cors(["http://localhost:3000", "chrome-extension://abcdefghijklmnopqrstuvwxyz123456"])[0] is False
    
def test_cors_placeholder():
    assert check_production_cors(["chrome-extension://your-extension-id"])[0] is False
    
def test_cors_missing_extension():
    assert check_production_cors(["https://example.com"])[0] is False

def test_validate_secret_custom_length():
    assert validate_secret('a' * 19 + 'b', min_length=20)[1] == 'PASS'
