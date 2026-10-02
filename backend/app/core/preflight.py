import sys
from typing import Tuple
from app.core.config import get_settings, Settings
import urllib.parse

WEAK_PLACEHOLDERS = {
    "your_github_oauth_app_client_id",
    "your_github_oauth_app_client_secret",
    "your_fernet_key_here",
    "your_state_secret_here",
    "your_gemini_api_key_here",
    "your_shared_secret_here",
    "your-extension-id"
}

WEAK_WORDS = {"changeme", "secret", "password"}

def validate_secret(secret_value: str, min_length: int = 32) -> Tuple[bool, str]:
    if not secret_value:
        return False, "MISSING"
    
    if len(secret_value) < min_length:
        return False, "UNSAFE DEFAULT"
    
    if len(set(secret_value)) == 1:
        return False, "UNSAFE DEFAULT"
        
    if secret_value in WEAK_PLACEHOLDERS:
        return False, "UNSAFE DEFAULT"
        
    if secret_value.lower() in WEAK_WORDS:
        return False, "UNSAFE DEFAULT"
        
    return True, "PASS"

def check_production_cors(allowed_origins: list[str]) -> Tuple[bool, str]:
    if not allowed_origins:
        return False, "MISSING"
        
    if "*" in allowed_origins:
        return False, "FAIL (Wildcard * not allowed)"
        
    has_valid_extension = False
    
    for origin in allowed_origins:
        if "localhost" in origin:
            return False, "FAIL (Localhost not allowed in production)"
            
        if origin.startswith("chrome-extension://"):
            ext_id = origin.replace("chrome-extension://", "")
            if ext_id == "your-extension-id" or len(ext_id) != 32:
                return False, "FAIL (Placeholder extension ID)"
            has_valid_extension = True

    if not has_valid_extension:
        return False, "FAIL (Missing production extension origin)"
        
    return True, "PASS"

def check_db_url(url: str, is_sync: bool = False) -> Tuple[bool, str]:
    if not url:
        return False, "MISSING"
    
    try:
        parsed = urllib.parse.urlparse(url)
        if is_sync:
            if not parsed.scheme.startswith("postgresql"):
                return False, "INVALID FORMAT"
        else:
            if not parsed.scheme.startswith("postgresql+asyncpg"):
                return False, "INVALID FORMAT"
    except Exception:
        return False, "INVALID FORMAT"
        
    return True, "PASS"

def run_preflight() -> bool:
    print("--- GitReview AI Production Preflight ---")
    settings = get_settings()
    all_passed = True
    
    def report(name: str, status: str):
        nonlocal all_passed
        print(f"{name:30} {status}")
        if not status.startswith("PASS"):
            all_passed = False

    if settings.app_env != "production":
        report("APP_ENV", "FAIL (not production)")
    else:
        report("APP_ENV", "PASS")
        
    if settings.debug:
        report("DEBUG", "FAIL (must be False in production)")
    else:
        report("DEBUG", "PASS")
        
    report("ALLOWED_ORIGINS", check_production_cors(settings.allowed_origins)[1])
    
    report("GITHUB_CLIENT_ID", validate_secret(settings.github_client_id, min_length=20)[1])
    report("GITHUB_CLIENT_SECRET", validate_secret(settings.github_client_secret)[1])
    
    if not settings.github_redirect_uri:
        report("GITHUB_REDIRECT_URI", "MISSING")
    elif "localhost" in settings.github_redirect_uri:
        report("GITHUB_REDIRECT_URI", "FAIL (localhost not allowed)")
    else:
        report("GITHUB_REDIRECT_URI", "PASS")
        
    report("STATE_SECRET", validate_secret(settings.state_secret)[1])
    report("ENCRYPTION_KEY", validate_secret(settings.encryption_key)[1])
    report("GEMINI_API_KEY", validate_secret(settings.gemini_api_key)[1])
    report("ACTIONS_SHARED_SECRET", validate_secret(settings.actions_shared_secret)[1])
    
    report("DATABASE_URL", check_db_url(settings.database_url)[1])
    report("DATABASE_URL_SYNC", check_db_url(settings.database_url_sync, is_sync=True)[1])
    
    return all_passed

if __name__ == "__main__":
    if not run_preflight():
        sys.exit(1)
    sys.exit(0)
