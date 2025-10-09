import requests
import os
from dotenv import load_dotenv
import logging
from fastapi import HTTPException

load_dotenv()
logger = logging.getLogger(__name__)

BASE_URL = f'{os.getenv("USER_BE_ORIGIN")}/api/v1'

def user_login(username: str, password: str):
    logger.info("Making login request to user service")
    url = f'{BASE_URL}/login/'
    body = {
        "username": username,
        "password": password,
        "grant_type": "password",
        "scope": "",
        "client_id": "",
        "client_secret": ""
    }

    try:
        response = requests.post(url, data=body, timeout=10)

        if response.status_code != 200:
            logger.info(f"Login failed with status {response.status_code}: {response.text}")
            raise HTTPException(status_code=response.status_code, detail=response.json())
        
        logger.debug("User Login successful")
        response_data = response.json()
        logger.debug(f"Response: {response_data}")
        return response_data
    
    except requests.exceptions.ConnectionError as e:
        logger.error(f"Connection error at {url}: {str(e)}")
        raise HTTPException(status_code=503, detail="Authentication service may be unavailable")
    
    except requests.exceptions.Timeout as e:
        logger.error(f"Connection timeout: {str(e)}")
        raise HTTPException(status_code=504, detail="Authentication timed out")
    
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        raise HTTPException(status_code=500, detail="An unexpected error has occurred")