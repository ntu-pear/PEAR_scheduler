from fastapi import Depends, FastAPI, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from typing import Optional
import base64, json, time, binascii
from pydantic import BaseModel, ValidationError
import logging

from pear_schedule.services.usersvc_util import user_login

logger = logging.getLogger(__name__)

# tells swaggerUI where tokens can be obtained (Authorise App tab)
# extracts tokens from future requests' authorisation headers
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="schedule/token")

class Token(BaseModel):
    access_token: str
    token_type: str

class JWTPayload(BaseModel):
    userId: str
    fullName: str
    email: str
    roleName: str
    sessionId: str

# conversion of an actual token to a JWTPayload model
def decode_jwtToken(token: str, bypass_auth: bool = False) -> Optional[JWTPayload]:
    try:
        header, payload, signature = token.split(".")

        # payload is base64URL encoded, jwt tokens in transmission omit padding (=)
        # base64 decoding requires input length to be a multiple of 4
        payload += "=" * (-len(payload) % 4)

        # decode to binaries, then to a utf-8 string
        decoded_payload = base64.urlsafe_b64decode(payload).decode("utf-8")
        parsed_payload_data = json.loads(decoded_payload)

        # exp must be NumericDate
        jwt_expiration = parsed_payload_data.get("exp")
        if jwt_expiration is None:
            if not bypass_auth:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token missing expiration")
            return None
        
        if jwt_expiration < int(time.time()):
            if not bypass_auth:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has expired")
            return None
        
        subject_identifier = parsed_payload_data.get("sub")
        if subject_identifier is None:
            if not bypass_auth:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token missing subject identifier")
            return None
        
        user_data = json.loads(subject_identifier)
        return JWTPayload(**user_data)
    
    except Exception as e:
        error_type = type(e).__name__
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"{error_type}: {str(e)}")

# get current user from incoming request, /token
def get_current_user(token: str = Depends(oauth2_scheme)) -> JWTPayload:
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return decode_jwtToken(token)

def get_role_name(payload: JWTPayload) -> Optional[str]:
    return getattr(payload, "roleName", None)

def is_supervisor(payload: JWTPayload) -> bool:
    return get_role_name(payload) == "SUPERVISOR"

async def generateAccessToken_onLogin(form_data: OAuth2PasswordRequestForm) -> Token:
    response = user_login(
        username = form_data.username,
        password = form_data.password
    )
    
    access_token = response.get("access_token")

    return Token(
        access_token = access_token,
        token_type = "bearer"
    )