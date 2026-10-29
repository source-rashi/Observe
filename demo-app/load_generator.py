import os
import time
import random
import logging
import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("load_generator")

TARGET_URL = os.getenv("TARGET_URL", "http://demo-app:8000").rstrip("/")

def run_loop():
    logger.info(f"Starting load generator against {TARGET_URL}")
    with httpx.Client(timeout=10.0) as client:
        while True:
            roll = random.random()
            try:
                if roll < 0.50:
                    client.get(f"{TARGET_URL}/products")
                elif roll < 0.80:
                    client.get(f"{TARGET_URL}/orders")
                elif roll < 0.95:
                    client.post(f"{TARGET_URL}/checkout")
                else:
                    client.get(f"{TARGET_URL}/health")
            except Exception as e:
                logger.debug(f"Request error (expected during chaos): {e}")

            # Sleep 100-200ms to achieve roughly 5-10 req/s
            time.sleep(random.uniform(0.10, 0.20))

if __name__ == "__main__":
    run_loop()
