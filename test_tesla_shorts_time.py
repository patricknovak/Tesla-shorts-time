import os
import logging
from digests.tesla_shorts_time import retry_with_backoff, get_stock_price

# Configure logging for the test
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

def test_environment_variables():
    """
    Test if all required environment variables are loaded.
    """
    required_env_vars = [
        "X_CONSUMER_KEY", "X_CONSUMER_SECRET", 
        "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET"
    ]
    for var in required_env_vars:
        assert os.getenv(var), f"Environment variable {var} is missing!"
    logging.info("All required environment variables are loaded.")

def test_ffmpeg_dependency():
    """
    Test if ffmpeg is installed and available.
    """
    result = subprocess.run(["which", "ffmpeg"], capture_output=True)
    assert result.returncode == 0, "ffmpeg is not installed!"
    logging.info("ffmpeg is installed and available.")

def test_stock_price_fetching():
    """
    Test if the stock price fetching function works.
    """
    ticker = os.getenv("TICKER_SYMBOL", "TSLA")
    price = retry_with_backoff(lambda: get_stock_price(ticker))
    assert price > 0, f"Failed to fetch stock price for {ticker}!"
    logging.info(f"Stock price for {ticker}: ${price:.2f}")

if __name__ == "__main__":
    logging.info("Starting tests for Tesla Shorts Time...")
    test_environment_variables()
    test_ffmpeg_dependency()
    test_stock_price_fetching()
    logging.info("All tests passed successfully!")